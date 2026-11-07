"""``PostgresThreadStore``: every thread's state in PostgreSQL, one turn per thread at a time.

Claiming a thread is one conditional ``INSERT ... ON CONFLICT DO UPDATE`` that takes a lease
(``busy_until``); a crashed process's lease simply expires. Message history lives in the
checkpointer's own tables; this store deletes it together with the thread. Every statement is
parameterised, and rows are decoded through ``storage.codec`` (a bad row reads as absent).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Table, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.usage_meter import CallUsage
from config.database import DatabaseSettings
from storage import codec
from storage.tables import (
    thread_answers,
    thread_pending,
    thread_tool_messages,
    thread_usage,
    thread_workspaces,
    threads,
)
from tools.schemas import ConfirmationRequest

Sessions = async_sessionmaker[AsyncSession]


def _idle() -> ColumnElement[bool]:
    """Condition: the thread holds no unexpired lease."""
    return or_(threads.c.busy_until.is_(None), threads.c.busy_until < func.now())


def _of(thread_id: str, table: Table) -> ColumnElement[bool]:
    return table.c.thread_id == thread_id


class PostgresThreadStore[WorkspaceT: BaseModel]:
    """The web program's thread store over a SQLAlchemy session factory and a checkpointer.

    Args:
        sessions: Factory of async sessions (one transaction per store call).
        checkpointer: Keeps each thread's messages; given to the agent, cleaned up here.
        settings: Provides the turn lease.
        workspace_model: The pydantic model a stored workspace must validate against.
    """

    def __init__(
        self,
        sessions: Sessions,
        checkpointer: BaseCheckpointSaver[str],
        settings: DatabaseSettings,
        workspace_model: type[WorkspaceT],
    ) -> None:
        self.checkpointer = checkpointer
        self._sessions = sessions
        self._lease = timedelta(seconds=settings.turn_lease_seconds)
        self._workspace_model = workspace_model

    # --- turns and lifetime ---------------------------------------------------------------

    async def claim(self, thread_id: str) -> bool:
        """Take the thread for a turn; False while another unexpired lease exists."""
        lease = func.now() + self._lease
        statement = (
            pg_insert(threads)
            .values(id=thread_id, busy_until=lease, last_used_at=func.now())
            .on_conflict_do_update(
                index_elements=[threads.c.id],
                set_={"busy_until": lease, "last_used_at": func.now()},
                where=_idle(),
            )
            .returning(threads.c.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def release(self, thread_id: str) -> None:
        """Clear the lease (safe to call more than once)."""
        statement = update(threads).where(threads.c.id == thread_id).values(busy_until=None)
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def touch(self, thread_id: str) -> None:
        """Mark the thread as most recently used, creating it when it is new."""
        statement = (
            pg_insert(threads)
            .values(id=thread_id)
            .on_conflict_do_update(
                index_elements=[threads.c.id],
                set_={"last_used_at": func.now()},
            )
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def holds(self, thread_id: str) -> bool:
        """Whether the thread exists."""
        statement = select(threads.c.id).where(threads.c.id == thread_id)
        async with self._sessions() as session:
            return (await session.execute(statement)).first() is not None

    async def running(self, thread_id: str) -> bool:
        """Whether the thread holds an unexpired lease."""
        statement = select(threads.c.id).where(threads.c.id == thread_id, ~_idle())
        async with self._sessions() as session:
            return (await session.execute(statement)).first() is not None

    async def reset(self, thread_id: str) -> bool:
        """Delete the thread and its checkpoints; False (nothing changed) while it runs."""
        statement = delete(threads).where(threads.c.id == thread_id, _idle())
        async with self._sessions.begin() as session:
            await session.execute(statement)
        if await self.running(thread_id):
            return False
        await self.checkpointer.adelete_thread(thread_id)
        return True

    async def purge_idle(self, older_than: timedelta) -> list[str]:
        """Delete idle threads unused for ``older_than``, with their checkpoints; their ids."""
        statement = (
            delete(threads)
            .where(threads.c.last_used_at < func.now() - older_than, _idle())
            .returning(threads.c.id)
        )
        async with self._sessions.begin() as session:
            purged = [row.id for row in await session.execute(statement)]
        for thread_id in purged:
            await self.checkpointer.adelete_thread(thread_id)
        return purged

    # --- messages -------------------------------------------------------------------------

    async def messages(self, thread_id: str) -> list[BaseMessage]:
        """The thread's conversation as of its last finished step (a copy)."""
        found = await self.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
        if found is None:
            return []
        return list(found.checkpoint["channel_values"].get("messages", []))

    # --- usage and tool messages (append-only, ordered by a per-thread seq) -----------------

    async def _next_seq(self, session: AsyncSession, table: Table, thread_id: str) -> int:
        """Lock the thread (creating it if new) and return the next free ``seq`` of ``table``."""
        await session.execute(pg_insert(threads).values(id=thread_id).on_conflict_do_nothing())
        await session.execute(
            select(threads.c.id).where(threads.c.id == thread_id).with_for_update(),
        )
        top = select(func.coalesce(func.max(table.c.seq), -1)).where(_of(thread_id, table))
        return int((await session.execute(top)).scalar_one()) + 1

    async def add_usage(self, thread_id: str, calls: Sequence[CallUsage]) -> None:
        """Add a finished turn's model calls to the thread's session usage."""
        if not calls:
            return
        async with self._sessions.begin() as session:
            first = await self._next_seq(session, thread_usage, thread_id)
            rows = [
                _usage_row(thread_id, first + offset, call) for offset, call in enumerate(calls)
            ]
            await session.execute(insert(thread_usage), rows)

    async def session_calls(self, thread_id: str) -> list[CallUsage]:
        """Every model call of the thread so far; rows that do not decode are left out."""
        columns = thread_usage.c
        statement = (
            select(
                columns.model,
                columns.input_tokens,
                columns.cached_input_tokens,
                columns.output_tokens,
            )
            .where(_of(thread_id, thread_usage))
            .order_by(columns.seq)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        decoded = (codec.usage_from_row(thread_id, *row) for row in rows)
        return [call for call in decoded if call is not None]

    async def add_tool_messages(self, thread_id: str, messages: Sequence[BaseMessage]) -> None:
        """Keep a thread's tool calls and results, from which its workspace is rebuilt."""
        if not messages:
            return
        async with self._sessions.begin() as session:
            first = await self._next_seq(session, thread_tool_messages, thread_id)
            rows = [
                {"thread_id": thread_id, "seq": first + offset, "message": codec.message_to_json(m)}
                for offset, m in enumerate(messages)
            ]
            await session.execute(insert(thread_tool_messages), rows)

    async def tool_messages(self, thread_id: str) -> list[BaseMessage]:
        """The thread's tool calls and results so far; rows that do not decode are left out."""
        statement = (
            select(thread_tool_messages.c.message)
            .where(_of(thread_id, thread_tool_messages))
            .order_by(thread_tool_messages.c.seq)
        )
        async with self._sessions() as session:
            raw = (await session.execute(statement)).scalars().all()
        decoded = (codec.message_from_json(item, thread_id) for item in raw)
        return [message for message in decoded if message is not None]

    # --- workspace and pending confirmation -------------------------------------------------

    async def _ensure(self, session: AsyncSession, thread_id: str) -> None:
        await session.execute(pg_insert(threads).values(id=thread_id).on_conflict_do_nothing())

    async def workspace(self, thread_id: str) -> WorkspaceT | None:
        """The workspace last stored for the thread; None when absent or not valid."""
        statement = select(thread_workspaces.c.state).where(_of(thread_id, thread_workspaces))
        async with self._sessions() as session:
            raw = (await session.execute(statement)).scalar_one_or_none()
        if raw is None:
            return None
        return codec.workspace_from_json(self._workspace_model, raw, thread_id)

    async def set_workspace(self, thread_id: str, state: WorkspaceT) -> None:
        """Remember the workspace just sent for the thread."""
        state_json = codec.workspace_to_json(state)
        statement = pg_insert(thread_workspaces).values(thread_id=thread_id, state=state_json)
        statement = statement.on_conflict_do_update(
            index_elements=[thread_workspaces.c.thread_id],
            set_={"state": state_json, "updated_at": func.now()},
        )
        async with self._sessions.begin() as session:
            await self._ensure(session, thread_id)
            await session.execute(statement)

    async def pending(self, thread_id: str) -> ConfirmationRequest | None:
        """The thread's open confirmation request; None when none is open or it is not valid."""
        statement = select(thread_pending.c.request).where(_of(thread_id, thread_pending))
        async with self._sessions() as session:
            raw = (await session.execute(statement)).scalar_one_or_none()
        return None if raw is None else codec.pending_from_json(raw, thread_id)

    async def set_pending(self, thread_id: str, request: ConfirmationRequest | None) -> None:
        """Open a confirmation request for the thread, or close it (None)."""
        async with self._sessions.begin() as session:
            if request is None:
                await session.execute(delete(thread_pending).where(_of(thread_id, thread_pending)))
                return
            await self._ensure(session, thread_id)
            stored = codec.pending_to_json(request)
            statement = pg_insert(thread_pending).values(thread_id=thread_id, request=stored)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[thread_pending.c.thread_id],
                    set_={"request": stored, "created_at": func.now()},
                ),
            )

    # --- the user's answers -----------------------------------------------------------------

    async def answers(self, thread_id: str) -> tuple[dict[str, float], frozenset[str]]:
        """The values the user supplied and the entries declined (copies); bad rows left out."""
        columns = thread_answers.c
        statement = select(columns.key, columns.value, columns.declined).where(
            _of(thread_id, thread_answers),
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        supplied: dict[str, float] = {}
        declined: set[str] = set()
        for row in rows:
            item = codec.answer_from_row(thread_id, *row)
            if item is None:
                continue
            key, value = item
            if value is None:
                declined.add(key)
            else:
                supplied[key] = value
        return supplied, frozenset(declined)

    async def record_answers(
        self,
        thread_id: str,
        supplied: Mapping[str, float],
        declined: Iterable[str],
    ) -> None:
        """Keep the user's answers; a supplied value is never replaced, and beats a decline."""
        async with self._sessions.begin() as session:
            await self._ensure(session, thread_id)
            await _insert_declined(session, thread_id, list(declined))
            await _insert_supplied(session, thread_id, supplied)


def _usage_row(thread_id: str, seq: int, call: CallUsage) -> dict[str, object]:
    return {
        "thread_id": thread_id,
        "seq": seq,
        "model": call.model,
        "input_tokens": call.input_tokens,
        "cached_input_tokens": call.cached_input_tokens,
        "output_tokens": call.output_tokens,
    }


async def _insert_declined(session: AsyncSession, thread_id: str, keys: list[str]) -> None:
    if not keys:
        return
    rows = [{"thread_id": thread_id, "key": key, "value": None, "declined": True} for key in keys]
    await session.execute(pg_insert(thread_answers).values(rows).on_conflict_do_nothing())


async def _insert_supplied(
    session: AsyncSession,
    thread_id: str,
    supplied: Mapping[str, float],
) -> None:
    if not supplied:
        return
    rows = [
        {"thread_id": thread_id, "key": key, "value": value, "declined": False}
        for key, value in supplied.items()
    ]
    statement = pg_insert(thread_answers).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[thread_answers.c.thread_id, thread_answers.c.key],
            set_={"value": statement.excluded.value, "declined": False},
            where=thread_answers.c.declined,
        ),
    )
