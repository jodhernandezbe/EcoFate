"""``PostgresThreadStore``: every thread's state in PostgreSQL, one turn per thread at a time.

A thread belongs to one user: every method takes a ``ThreadKey`` (owner and thread id) and puts
both in its ``WHERE``, so one user's id can never reach another user's rows, and the checkpointer
is addressed by the owner-scoped ``ThreadKey.checkpoint_id``. The only operations across users
are ``purge_idle`` (retention) and, for one owner, ``forget_owner`` (account deletion).

Claiming a thread is one conditional ``INSERT ... ON CONFLICT DO UPDATE`` that takes a lease
(``busy_until``); a crashed process's lease simply expires. Message history lives in the
checkpointer's own tables; this store deletes it together with the thread. Every statement is
parameterised, and rows are decoded through ``storage.codec`` (a bad row reads as absent).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from uuid import UUID

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel
from sqlalchemy import (
    ColumnElement,
    Table,
    and_,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.usage_meter import CallUsage
from config.database import DatabaseSettings
from storage import codec
from storage.keys import ThreadKey
from storage.tables import (
    thread_answers,
    thread_pending,
    thread_tool_messages,
    thread_usage,
    thread_workspaces,
    threads,
)
from storage.turns import TurnRepository
from tools.schemas import ConfirmationRequest

Sessions = async_sessionmaker[AsyncSession]


def _idle() -> ColumnElement[bool]:
    """Condition: the thread holds no unexpired lease."""
    return or_(threads.c.busy_until.is_(None), threads.c.busy_until < func.now())


def _mine(key: ThreadKey) -> ColumnElement[bool]:
    """Condition: the ``threads`` row of this owner's thread."""
    return and_(threads.c.owner_id == key.owner_id, threads.c.id == key.thread_id)


def _of(key: ThreadKey, table: Table) -> ColumnElement[bool]:
    """Condition: the rows of ``table`` that belong to this owner's thread."""
    return and_(table.c.owner_id == key.owner_id, table.c.thread_id == key.thread_id)


def _scope(key: ThreadKey) -> dict[str, object]:
    """The owner and thread columns of a row to insert."""
    return {"owner_id": key.owner_id, "thread_id": key.thread_id}


def _new_thread(key: ThreadKey) -> PgInsert:
    return pg_insert(threads).values(owner_id=key.owner_id, id=key.thread_id)


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
        self.turns = TurnRepository(sessions)
        self._sessions = sessions
        self._lease = timedelta(seconds=settings.turn_lease_seconds)
        self._workspace_model = workspace_model

    # --- turns and lifetime ---------------------------------------------------------------

    async def claim(self, key: ThreadKey) -> bool:
        """Take the thread for a turn; False while another unexpired lease exists."""
        lease = func.now() + self._lease
        statement = (
            _new_thread(key)
            .values(busy_until=lease, last_used_at=func.now())
            .on_conflict_do_update(
                index_elements=[threads.c.owner_id, threads.c.id],
                set_={"busy_until": lease, "last_used_at": func.now()},
                where=_idle(),
            )
            .returning(threads.c.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def release(self, key: ThreadKey) -> None:
        """Clear the lease (safe to call more than once)."""
        statement = update(threads).where(_mine(key)).values(busy_until=None)
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def touch(self, key: ThreadKey) -> None:
        """Mark the thread as most recently used, creating it when it is new."""
        statement = _new_thread(key).on_conflict_do_update(
            index_elements=[threads.c.owner_id, threads.c.id],
            set_={"last_used_at": func.now()},
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def holds(self, key: ThreadKey) -> bool:
        """Whether the owner has this thread."""
        statement = select(threads.c.id).where(_mine(key))
        async with self._sessions() as session:
            return (await session.execute(statement)).first() is not None

    async def running(self, key: ThreadKey) -> bool:
        """Whether the thread holds an unexpired lease."""
        statement = select(threads.c.id).where(_mine(key), ~_idle())
        async with self._sessions() as session:
            return (await session.execute(statement)).first() is not None

    async def reset(self, key: ThreadKey) -> bool:
        """Delete the thread and its checkpoints; False (nothing changed) while it runs."""
        statement = delete(threads).where(_mine(key), _idle())
        async with self._sessions.begin() as session:
            await session.execute(statement)
        if await self.running(key):
            return False
        await self.checkpointer.adelete_thread(key.checkpoint_id)
        return True

    async def purge_idle(self, older_than: timedelta) -> list[ThreadKey]:
        """Delete idle threads of every user unused for ``older_than``, with their checkpoints."""
        statement = (
            delete(threads)
            .where(threads.c.last_used_at < func.now() - older_than, _idle())
            .returning(threads.c.owner_id, threads.c.id)
        )
        async with self._sessions.begin() as session:
            purged = [ThreadKey(row.owner_id, row.id) for row in await session.execute(statement)]
        for key in purged:
            await self.checkpointer.adelete_thread(key.checkpoint_id)
        return purged

    async def forget_owner(self, owner_id: UUID) -> int:
        """Delete every thread of one user, running or not, with its checkpoints (account
        deletion); how many there were."""
        owned = select(threads.c.id).where(threads.c.owner_id == owner_id)
        async with self._sessions.begin() as session:
            ids = list((await session.execute(owned)).scalars())
            await session.execute(delete(threads).where(threads.c.owner_id == owner_id))
        for thread_id in ids:
            await self.checkpointer.adelete_thread(ThreadKey(owner_id, thread_id).checkpoint_id)
        return len(ids)

    # --- messages -------------------------------------------------------------------------

    async def messages(self, key: ThreadKey) -> list[BaseMessage]:
        """The thread's conversation as of its last finished step (a copy)."""
        config: RunnableConfig = {"configurable": {"thread_id": key.checkpoint_id}}
        found = await self.checkpointer.aget_tuple(config)
        if found is None:
            return []
        return list(found.checkpoint["channel_values"].get("messages", []))

    # --- usage and tool messages (append-only, ordered by a per-thread seq) -----------------

    async def _next_seq(self, session: AsyncSession, table: Table, key: ThreadKey) -> int:
        """Lock the thread (creating it if new) and return the next free ``seq`` of ``table``."""
        await session.execute(_new_thread(key).on_conflict_do_nothing())
        await session.execute(select(threads.c.id).where(_mine(key)).with_for_update())
        top = select(func.coalesce(func.max(table.c.seq), -1)).where(_of(key, table))
        return int((await session.execute(top)).scalar_one()) + 1

    async def add_usage(
        self,
        key: ThreadKey,
        calls: Sequence[CallUsage],
        turn_id: str | None = None,
    ) -> None:
        """Add a finished turn's (or resumed segment's) model calls to the thread's usage."""
        if not calls:
            return
        async with self._sessions.begin() as session:
            first = await self._next_seq(session, thread_usage, key)
            rows = [
                _usage_row(key, first + offset, call) | {"turn_id": turn_id}
                for offset, call in enumerate(calls)
            ]
            await session.execute(insert(thread_usage), rows)

    async def session_calls(self, key: ThreadKey) -> list[CallUsage]:
        """Every model call of the thread so far; rows that do not decode are left out."""
        return await self._calls(key, None)

    async def turn_calls(self, key: ThreadKey, turn_id: str) -> list[CallUsage]:
        """Every model call of one turn, its resumed segments included; bad rows left out."""
        return await self._calls(key, turn_id)

    async def _calls(self, key: ThreadKey, turn_id: str | None) -> list[CallUsage]:
        columns = thread_usage.c
        statement = (
            select(
                columns.model,
                columns.input_tokens,
                columns.cached_input_tokens,
                columns.output_tokens,
            )
            .where(_of(key, thread_usage))
            .order_by(columns.seq)
        )
        if turn_id is not None:
            statement = statement.where(columns.turn_id == turn_id)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        decoded = (codec.usage_from_row(key.thread_id, *row) for row in rows)
        return [call for call in decoded if call is not None]

    async def add_tool_messages(self, key: ThreadKey, messages: Sequence[BaseMessage]) -> None:
        """Keep a thread's tool calls and results, from which its workspace is rebuilt."""
        if not messages:
            return
        async with self._sessions.begin() as session:
            first = await self._next_seq(session, thread_tool_messages, key)
            rows = [
                _scope(key) | {"seq": first + offset, "message": codec.message_to_json(m)}
                for offset, m in enumerate(messages)
            ]
            await session.execute(insert(thread_tool_messages), rows)

    async def tool_messages(self, key: ThreadKey) -> list[BaseMessage]:
        """The thread's tool calls and results so far; rows that do not decode are left out."""
        statement = (
            select(thread_tool_messages.c.message)
            .where(_of(key, thread_tool_messages))
            .order_by(thread_tool_messages.c.seq)
        )
        async with self._sessions() as session:
            raw = (await session.execute(statement)).scalars().all()
        decoded = (codec.message_from_json(item, key.thread_id) for item in raw)
        return [message for message in decoded if message is not None]

    # --- workspace and pending confirmation -------------------------------------------------

    async def workspace(self, key: ThreadKey) -> WorkspaceT | None:
        """The workspace last stored for the thread; None when absent or not valid."""
        statement = select(thread_workspaces.c.state).where(_of(key, thread_workspaces))
        async with self._sessions() as session:
            raw = (await session.execute(statement)).scalar_one_or_none()
        if raw is None:
            return None
        return codec.workspace_from_json(self._workspace_model, raw, key.thread_id)

    async def set_workspace(self, key: ThreadKey, state: WorkspaceT) -> None:
        """Remember the workspace just sent for the thread."""
        state_json = codec.workspace_to_json(state)
        statement = pg_insert(thread_workspaces).values(**_scope(key), state=state_json)
        statement = statement.on_conflict_do_update(
            index_elements=[thread_workspaces.c.owner_id, thread_workspaces.c.thread_id],
            set_={"state": state_json, "updated_at": func.now()},
        )
        async with self._sessions.begin() as session:
            await session.execute(_new_thread(key).on_conflict_do_nothing())
            await session.execute(statement)

    async def pending(self, key: ThreadKey) -> ConfirmationRequest | None:
        """The thread's open confirmation request; None when none is open or it is not valid."""
        statement = select(thread_pending.c.request).where(_of(key, thread_pending))
        async with self._sessions() as session:
            raw = (await session.execute(statement)).scalar_one_or_none()
        return None if raw is None else codec.pending_from_json(raw, key.thread_id)

    async def set_pending(self, key: ThreadKey, request: ConfirmationRequest | None) -> None:
        """Open a confirmation request for the thread, or close it (None)."""
        async with self._sessions.begin() as session:
            if request is None:
                await session.execute(delete(thread_pending).where(_of(key, thread_pending)))
                return
            await session.execute(_new_thread(key).on_conflict_do_nothing())
            stored = codec.pending_to_json(request)
            statement = pg_insert(thread_pending).values(**_scope(key), request=stored)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[thread_pending.c.owner_id, thread_pending.c.thread_id],
                    set_={"request": stored, "created_at": func.now()},
                ),
            )

    # --- the user's answers -----------------------------------------------------------------

    async def answers(self, key: ThreadKey) -> tuple[dict[str, float], frozenset[str]]:
        """The values the user supplied and the entries declined (copies); bad rows left out."""
        columns = thread_answers.c
        statement = select(columns.key, columns.value, columns.declined).where(
            _of(key, thread_answers),
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        supplied: dict[str, float] = {}
        declined: set[str] = set()
        for row in rows:
            item = codec.answer_from_row(key.thread_id, *row)
            if item is None:
                continue
            name, value = item
            if value is None:
                declined.add(name)
            else:
                supplied[name] = value
        return supplied, frozenset(declined)

    async def record_answers(
        self,
        key: ThreadKey,
        supplied: Mapping[str, float],
        declined: Iterable[str],
    ) -> None:
        """Keep the user's answers; a supplied value is never replaced, and beats a decline."""
        async with self._sessions.begin() as session:
            await session.execute(_new_thread(key).on_conflict_do_nothing())
            await _insert_declined(session, key, list(declined))
            await _insert_supplied(session, key, supplied)


def _usage_row(key: ThreadKey, seq: int, call: CallUsage) -> dict[str, object]:
    return _scope(key) | {
        "seq": seq,
        "model": call.model,
        "input_tokens": call.input_tokens,
        "cached_input_tokens": call.cached_input_tokens,
        "output_tokens": call.output_tokens,
    }


async def _insert_declined(session: AsyncSession, key: ThreadKey, names: list[str]) -> None:
    if not names:
        return
    rows = [_scope(key) | {"key": name, "value": None, "declined": True} for name in names]
    await session.execute(pg_insert(thread_answers).values(rows).on_conflict_do_nothing())


async def _insert_supplied(
    session: AsyncSession,
    key: ThreadKey,
    supplied: Mapping[str, float],
) -> None:
    if not supplied:
        return
    rows = [
        _scope(key) | {"key": name, "value": value, "declined": False}
        for name, value in supplied.items()
    ]
    statement = pg_insert(thread_answers).values(rows)
    answers = thread_answers.c
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[answers.owner_id, answers.thread_id, answers.key],
            set_={"value": statement.excluded.value, "declined": False},
            where=answers.declined,
        ),
    )
