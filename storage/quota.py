"""``QuotaRepository``: each user's agent turns per UTC day (the daily quota) in PostgreSQL.

Counting is one atomic ``INSERT ... ON CONFLICT DO UPDATE ... WHERE turns < limit RETURNING``:
no row comes back when the limit is reached, so concurrent requests, even in other processes,
never exceed it. The day is the database's UTC date, never a process clock. A refund marks the
turn's record first (``turns.quota_refunded``), so a turn is given back at most once. Every
method names the user in its ``WHERE``; the only call across users is the retention purge.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, Date, Update, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storage.tables import daily_turn_usage, turns

Sessions = async_sessionmaker[AsyncSession]
_COLUMNS = daily_turn_usage.c


def utc_today() -> ColumnElement[date]:
    """The database's current UTC date."""
    return cast(func.timezone("UTC", func.now()), Date)


def _give_back(user_id: UUID, day: date) -> Update:
    return (
        update(daily_turn_usage)
        .where(_COLUMNS.user_id == user_id, _COLUMNS.day == day)
        .values(turns=func.greatest(_COLUMNS.turns - 1, 0))
    )


class QuotaRepository:
    """Counts turns per user and day.

    Args:
        sessions: Factory of async sessions (one transaction per call).
        today: The expression naming the current day; the database's UTC date unless a test
            fixes it.
    """

    def __init__(self, sessions: Sessions, today: ColumnElement[date] | None = None) -> None:
        self._sessions = sessions
        self._today = today if today is not None else utc_today()

    async def consume(self, user_id: UUID, limit: int) -> int | None:
        """Count one turn for ``user_id`` today while below ``limit``.

        Returns:
            The turns counted today including this one; None when the limit was reached (and
            nothing was counted).
        """
        insert = pg_insert(daily_turn_usage).values(user_id=user_id, day=self._today, turns=1)
        statement = insert.on_conflict_do_update(
            index_elements=[_COLUMNS.user_id, _COLUMNS.day],
            set_={"turns": _COLUMNS.turns + 1},
            where=_COLUMNS.turns < limit,
        ).returning(_COLUMNS.turns)
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).scalar_one_or_none()

    async def refund(self, user_id: UUID, turn_id: str) -> bool:
        """Give back the turn ``turn_id`` of ``user_id``, once.

        The day given back is the UTC day the turn record was created on. Returns False (and
        changes nothing) when the turn is not the user's or was refunded already.
        """
        mark = (
            update(turns)
            .where(turns.c.id == turn_id, turns.c.user_id == user_id, ~turns.c.quota_refunded)
            .values(quota_refunded=True)
            .returning(cast(func.timezone("UTC", turns.c.created_at), Date))
        )
        async with self._sessions.begin() as session:
            day = (await session.execute(mark)).scalar_one_or_none()
            if day is None:
                return False
            await session.execute(_give_back(user_id, day))
            return True

    async def usage(self, user_id: UUID) -> int:
        """The turns counted for ``user_id`` today (0 when none)."""
        statement = select(_COLUMNS.turns).where(
            _COLUMNS.user_id == user_id,
            _COLUMNS.day == self._today,
        )
        async with self._sessions() as session:
            return (await session.execute(statement)).scalar_one_or_none() or 0

    async def purge_usage(self, older_than: timedelta) -> int:
        """Delete the rows of every user older than ``older_than``; how many were deleted."""
        statement = (
            delete(daily_turn_usage)
            .where(_COLUMNS.day < self._today - older_than)
            .returning(_COLUMNS.user_id)
        )
        async with self._sessions.begin() as session:
            return len((await session.execute(statement)).all())
