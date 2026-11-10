"""``SessionRepository``: signed-in sessions in PostgreSQL.

Only the SHA-256 hash of the session token is stored, so a leaked row is not a usable cookie.
A session ends at its idle expiry (pushed forward by each request) or its absolute expiry,
whichever is first; an expired session is deleted when it is presented.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Executable

from storage import codec
from storage.account_model import User
from storage.tables import sessions as session_table
from storage.tables import users

Sessions = async_sessionmaker[AsyncSession]
_COLUMNS = session_table.c


def _expired() -> ColumnElement[bool]:
    return (_COLUMNS.idle_expires_at <= func.now()) | (_COLUMNS.absolute_expires_at <= func.now())


def _touch(token_hash: str, idle_seconds: int) -> Executable:
    """Move a session's idle expiry forward (never past its absolute one); its user."""
    idle = func.now() + timedelta(seconds=idle_seconds)
    return (
        update(session_table)
        .where(_COLUMNS.token_hash == token_hash)
        .values(
            last_seen_at=func.now(),
            idle_expires_at=func.least(idle, _COLUMNS.absolute_expires_at),
        )
        .returning(_COLUMNS.user_id)
    )


class SessionRepository:
    """Creates, resolves and revokes sessions.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(
        self,
        token_hash: str,
        user_id: UUID,
        *,
        idle_seconds: int,
        absolute_seconds: int,
    ) -> None:
        """Store a new session for the user with its two expiries."""
        statement = insert(session_table).values(
            token_hash=token_hash,
            user_id=user_id,
            idle_expires_at=func.now() + timedelta(seconds=idle_seconds),
            absolute_expires_at=func.now() + timedelta(seconds=absolute_seconds),
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def resolve(self, token_hash: str, idle_seconds: int) -> User | None:
        """The account behind a live session, whose idle expiry moves forward; None (and an
        expired session deleted) otherwise."""
        gone = delete(session_table).where(_COLUMNS.token_hash == token_hash, _expired())
        async with self._sessions.begin() as session:
            await session.execute(gone)
            touched = await session.execute(_touch(token_hash, idle_seconds))
            user_id: UUID | None = touched.scalar_one_or_none()
            if user_id is None:
                return None
            row = (await session.execute(select(users).where(users.c.id == user_id))).mappings()
            return codec.user_from_row(row.first())

    async def revoke(self, token_hash: str) -> bool:
        """End one session; whether it existed."""
        statement = delete(session_table).where(_COLUMNS.token_hash == token_hash)
        async with self._sessions.begin() as session:
            return len((await session.execute(statement.returning(_COLUMNS.user_id))).all()) > 0

    async def revoke_all(self, user_id: UUID, *, keep: str | None = None) -> int:
        """End every session of the user, except the one hashed ``keep``; how many ended."""
        statement = delete(session_table).where(_COLUMNS.user_id == user_id)
        if keep is not None:
            statement = statement.where(_COLUMNS.token_hash != keep)
        async with self._sessions.begin() as session:
            return len((await session.execute(statement.returning(_COLUMNS.user_id))).all())

    async def purge_expired(self) -> int:
        """Delete every expired session; how many."""
        async with self._sessions.begin() as session:
            expired = delete(session_table).where(_expired()).returning(_COLUMNS.user_id)
            return len((await session.execute(expired)).all())
