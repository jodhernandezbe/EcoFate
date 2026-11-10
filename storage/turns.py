"""``TurnRepository``: every chat turn's durable status in PostgreSQL.

At most one turn per thread of a user is ``queued`` or ``running`` (the partial unique index
``uq_turns_open_thread``), so a second turn is refused even when it reaches another process.
Every method takes the owner (a ``ThreadKey``, or the owner id with a turn id) and puts it in its
``WHERE``: a turn of another user is never found. The one exception is ``interrupt_all_open``,
the server's own start-up recovery.
Each call is one transaction; a status change is checked against the allowed moves of
``storage.turn_model`` with the row locked, so an illegal move raises and changes nothing.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import ColumnElement, RowMapping, Update, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Executable

from storage import codec
from storage.keys import ThreadKey
from storage.tables import threads, turns
from storage.turn_model import (
    OPEN_STATUSES,
    REASONED_STATUSES,
    Turn,
    TurnStatus,
    TurnTransitionError,
    check_transition,
)

Sessions = async_sessionmaker[AsyncSession]
_OPEN = turns.c.status.in_([status.value for status in OPEN_STATUSES])


def _decoded(row: RowMapping | None) -> Turn | None:
    return None if row is None else codec.turn_from_row({str(k): v for k, v in row.items()})


def _mine(owner_id: UUID, turn_id: str) -> ColumnElement[bool]:
    return (turns.c.id == turn_id) & (turns.c.user_id == owner_id)


def _of(key: ThreadKey) -> ColumnElement[bool]:
    return (turns.c.user_id == key.owner_id) & (turns.c.thread_id == key.thread_id)


def _changes(target: TurnStatus, reason: str | None) -> dict[str, object]:
    """The columns a move to ``target`` sets (the reason only on interrupted or failed)."""
    values: dict[str, object] = {"status": target.value, "reason": reason, "updated_at": func.now()}
    if target is TurnStatus.RUNNING:
        values |= {"started_at": func.coalesce(turns.c.started_at, func.now()), "finished_at": None}
    if target in (TurnStatus.COMPLETED, TurnStatus.FAILED):
        values["finished_at"] = func.now()
    return values


def _check_reason(target: TurnStatus, reason: str | None) -> None:
    if (reason is not None) != (target in REASONED_STATUSES):
        raise ValueError(f"a {target} turn {'needs' if reason is None else 'takes no'} reason")


def _begin(key: ThreadKey) -> Executable:
    """Insert a running turn, unless the thread already has an open one."""
    return (
        pg_insert(turns)
        .values(
            id=uuid.uuid4().hex,
            user_id=key.owner_id,
            thread_id=key.thread_id,
            status=TurnStatus.RUNNING.value,
            started_at=func.now(),
        )
        .on_conflict_do_nothing(
            index_elements=[turns.c.user_id, turns.c.thread_id],
            index_where=_OPEN,
        )
        .returning(*turns.c)
    )


class TurnRepository:
    """Records turns and moves them through their statuses.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def begin(self, key: ThreadKey) -> Turn | None:
        """Record a new running turn of the thread; None while the thread has an open turn."""
        new_thread = (
            pg_insert(threads)
            .values(owner_id=key.owner_id, id=key.thread_id)
            .on_conflict_do_nothing()
        )
        async with self._sessions.begin() as session:
            await session.execute(new_thread)
            return _decoded((await session.execute(_begin(key))).mappings().first())

    async def resume(self, owner_id: UUID, turn_id: str, max_resumes: int) -> Turn | None:
        """Move an interrupted turn of the owner back to running and count the resume.

        Returns None, changing nothing, when the owner has no such turn, it is not interrupted,
        has been resumed ``max_resumes`` times, or its thread already has an open turn.
        """
        statement = (
            update(turns)
            .where(
                _mine(owner_id, turn_id),
                turns.c.status == TurnStatus.INTERRUPTED.value,
                turns.c.resume_count < max_resumes,
            )
            .values(resume_count=turns.c.resume_count + 1, **_changes(TurnStatus.RUNNING, None))
            .returning(*turns.c)
        )
        try:
            async with self._sessions.begin() as session:
                return _decoded((await session.execute(statement)).mappings().first())
        except IntegrityError:  # another turn of the thread became open first
            return None

    async def move(
        self,
        owner_id: UUID,
        turn_id: str,
        target: TurnStatus,
        reason: str | None = None,
    ) -> Turn:
        """Move the owner's turn to ``target`` (with its reason when interrupted or failed).

        Raises:
            TurnTransitionError: The owner has no such turn, or it cannot reach ``target`` from
                its status; nothing changed.
            ValueError: ``reason`` is missing for interrupted or failed, or given otherwise.
        """
        _check_reason(target, reason)
        async with self._sessions.begin() as session:
            current = await self._locked_status(session, owner_id, turn_id)
            check_transition(turn_id, current, target)
            statement = self._move_statement(owner_id, turn_id, target, reason)
            moved = _decoded((await session.execute(statement)).mappings().first())
        if moved is None:
            raise TurnTransitionError(f"turn {turn_id} could not be read back")
        return moved

    async def _locked_status(
        self,
        session: AsyncSession,
        owner_id: UUID,
        turn_id: str,
    ) -> TurnStatus:
        query = select(turns.c.status).where(_mine(owner_id, turn_id)).with_for_update()
        status = (await session.execute(query)).scalar_one_or_none()
        if status is None:
            raise TurnTransitionError(f"turn {turn_id} does not exist")
        return TurnStatus(status)

    @staticmethod
    def _move_statement(
        owner_id: UUID,
        turn_id: str,
        target: TurnStatus,
        reason: str | None,
    ) -> Update:
        changes = _changes(target, reason)
        return update(turns).where(_mine(owner_id, turn_id)).values(**changes).returning(*turns.c)

    async def abandon(self, owner_id: UUID, turn_id: str, reason: str) -> bool:
        """Interrupt the owner's turn if it is still open (its stream ended without a status);
        safe to repeat. Whether it was open."""
        return bool(await self._interrupt(_mine(owner_id, turn_id), reason))

    async def interrupt_open(self, key: ThreadKey, reason: str) -> None:
        """Interrupt the open turn of one thread, if it has one."""
        await self._interrupt(_of(key), reason)

    async def interrupt_all_open(self, reason: str) -> list[ThreadKey]:
        """Interrupt every open turn of every user (the server's start-up recovery only)."""
        return await self._interrupt(None, reason)

    async def _interrupt(self, where: ColumnElement[bool] | None, reason: str) -> list[ThreadKey]:
        statement = update(turns).where(_OPEN)
        if where is not None:
            statement = statement.where(where)
        changes = _changes(TurnStatus.INTERRUPTED, reason)
        statement = statement.values(**changes).returning(turns.c.user_id, turns.c.thread_id)
        async with self._sessions.begin() as session:
            return [
                ThreadKey(row.user_id, row.thread_id) for row in await session.execute(statement)
            ]

    async def latest(self, key: ThreadKey) -> Turn | None:
        """The thread's most recent turn; None when it has none (or it does not decode)."""
        query = (
            select(turns)
            .where(_of(key))
            .order_by(turns.c.created_at.desc(), turns.c.id.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            return _decoded((await session.execute(query)).mappings().first())
