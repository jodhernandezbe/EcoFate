"""``TurnRepository``: every chat turn's durable status in PostgreSQL.

At most one turn per thread is ``queued`` or ``running`` (the partial unique index
``uq_turns_open_thread``), so a second turn is refused even when it reaches another process.
Each call is one transaction; a status change is checked against the allowed moves of
``storage.turn_model`` with the row locked, so an illegal move raises and changes nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, RowMapping, Update, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storage import codec
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


class TurnRepository:
    """Records turns and moves them through their statuses.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def begin(self, thread_id: str) -> Turn | None:
        """Record a new running turn of the thread; None while the thread has an open turn."""
        statement = (
            pg_insert(turns)
            .values(
                id=uuid.uuid4().hex,
                thread_id=thread_id,
                status=TurnStatus.RUNNING.value,
                started_at=func.now(),
            )
            .on_conflict_do_nothing(index_elements=[turns.c.thread_id], index_where=_OPEN)
            .returning(*turns.c)
        )
        async with self._sessions.begin() as session:
            await session.execute(pg_insert(threads).values(id=thread_id).on_conflict_do_nothing())
            return _decoded((await session.execute(statement)).mappings().first())

    async def resume(self, turn_id: str, max_resumes: int) -> Turn | None:
        """Move an interrupted turn back to running and count the resume.

        Returns None, changing nothing, when the turn is not interrupted, has been resumed
        ``max_resumes`` times, or its thread already has an open turn.
        """
        statement = (
            update(turns)
            .where(
                turns.c.id == turn_id,
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

    async def move(self, turn_id: str, target: TurnStatus, reason: str | None = None) -> Turn:
        """Move a turn to ``target`` (with its reason when interrupted or failed).

        Raises:
            TurnTransitionError: The turn does not exist or cannot reach ``target`` from its
                status; nothing changed.
            ValueError: ``reason`` is missing for interrupted or failed, or given otherwise.
        """
        _check_reason(target, reason)
        async with self._sessions.begin() as session:
            current = await self._locked_status(session, turn_id)
            check_transition(turn_id, current, target)
            statement = self._move_statement(turn_id, target, reason)
            moved = _decoded((await session.execute(statement)).mappings().first())
        if moved is None:
            raise TurnTransitionError(f"turn {turn_id} could not be read back")
        return moved

    async def _locked_status(self, session: AsyncSession, turn_id: str) -> TurnStatus:
        query = select(turns.c.status).where(turns.c.id == turn_id).with_for_update()
        status = (await session.execute(query)).scalar_one_or_none()
        if status is None:
            raise TurnTransitionError(f"turn {turn_id} does not exist")
        return TurnStatus(status)

    @staticmethod
    def _move_statement(turn_id: str, target: TurnStatus, reason: str | None) -> Update:
        changes = _changes(target, reason)
        return update(turns).where(turns.c.id == turn_id).values(**changes).returning(*turns.c)

    async def abandon(self, turn_id: str, reason: str) -> bool:
        """Interrupt the turn if it is still open (its stream ended without a status); safe to
        repeat. Whether it was open."""
        return bool(await self._interrupt(turns.c.id == turn_id, reason))

    async def interrupt_open(self, reason: str, thread_id: str | None = None) -> list[str]:
        """Interrupt every open turn (of one thread, when given); the threads they belong to."""
        where = turns.c.thread_id == thread_id if thread_id is not None else None
        return await self._interrupt(where, reason)

    async def _interrupt(self, where: ColumnElement[bool] | None, reason: str) -> list[str]:
        statement = update(turns).where(_OPEN)
        if where is not None:
            statement = statement.where(where)
        changes = _changes(TurnStatus.INTERRUPTED, reason)
        statement = statement.values(**changes).returning(turns.c.thread_id)
        async with self._sessions.begin() as session:
            return [row.thread_id for row in await session.execute(statement)]

    async def latest(self, thread_id: str) -> Turn | None:
        """The thread's most recent turn; None when it has none (or it does not decode)."""
        query = (
            select(turns)
            .where(turns.c.thread_id == thread_id)
            .order_by(turns.c.created_at.desc(), turns.c.id.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            return _decoded((await session.execute(query)).mappings().first())
