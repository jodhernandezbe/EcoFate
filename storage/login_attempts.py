"""``LoginAttemptRepository``: failed sign-in and recovery attempts per key and window.

A key is ``email:<normalised address>`` or ``ip:<client address>``. The first failure opens a
window; failures inside it add up; the first failure after it ends starts a new one. Counting
is one atomic upsert, so concurrent failures are all counted.
"""

from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storage.tables import login_attempts

Sessions = async_sessionmaker[AsyncSession]
_COLUMNS = login_attempts.c


class LoginAttemptRepository:
    """Counts failures and says when a key may try again.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def record_failure(self, key: str, window_seconds: int) -> int:
        """Count one failed attempt for ``key``; the failures in its current window."""
        stale = login_attempts.c.window_start <= func.now() - timedelta(seconds=window_seconds)
        insert = pg_insert(login_attempts).values(key=key, window_start=func.now(), count=1)
        statement = insert.on_conflict_do_update(
            index_elements=[_COLUMNS.key],
            set_={
                "count": case((stale, 1), else_=_COLUMNS.count + 1),
                "window_start": case((stale, func.now()), else_=_COLUMNS.window_start),
            },
        ).returning(_COLUMNS.count)
        async with self._sessions.begin() as session:
            return int((await session.execute(statement)).scalar_one())

    async def retry_after(self, key: str, window_seconds: int, limit: int) -> int | None:
        """Seconds until ``key`` may try again when it reached ``limit`` failures in its window;
        None when it may try now."""
        statement = select(
            _COLUMNS.count,
            _COLUMNS.window_start + timedelta(seconds=window_seconds) - func.now(),
        ).where(_COLUMNS.key == key)
        async with self._sessions() as session:
            row = (await session.execute(statement)).first()
        if row is None or row[0] < limit or row[1] <= timedelta(0):
            return None
        return max(1, math.ceil(row[1].total_seconds()))

    async def clear(self, key: str) -> None:
        """Forget the failures of ``key`` (after a successful sign-in)."""
        async with self._sessions.begin() as session:
            await session.execute(delete(login_attempts).where(_COLUMNS.key == key))
