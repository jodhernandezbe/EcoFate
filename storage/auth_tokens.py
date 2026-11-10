"""``AuthTokenRepository``: single-use emailed tokens (verification and recovery).

Only the token's SHA-256 hash is stored. Using a token is one conditional ``UPDATE ...
RETURNING``, so two concurrent uses cannot both succeed. A new token for the same account and
purpose replaces the unused older ones.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import Delete, delete, func, insert, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storage.account_model import TokenPurpose
from storage.tables import auth_tokens

Sessions = async_sessionmaker[AsyncSession]
_COLUMNS = auth_tokens.c


class AuthTokenRepository:
    """Issues, consumes and invalidates tokens.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def issue(
        self,
        user_id: UUID,
        purpose: TokenPurpose,
        token_hash: str,
        ttl_seconds: int,
    ) -> None:
        """Store a new token and drop the user's unused older ones of the same purpose."""
        statement = insert(auth_tokens).values(
            purpose=purpose.value,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=func.now() + timedelta(seconds=ttl_seconds),
        )
        async with self._sessions.begin() as session:
            await session.execute(_unused(user_id, purpose))
            await session.execute(statement)

    async def consume(self, purpose: TokenPurpose, token_hash: str) -> UUID | None:
        """Use a valid token once; the account it belongs to, or None (nothing changed) when it
        is unknown, of another purpose, expired or already used."""
        statement = (
            update(auth_tokens)
            .where(
                _COLUMNS.token_hash == token_hash,
                _COLUMNS.purpose == purpose.value,
                _COLUMNS.used_at.is_(None),
                _COLUMNS.expires_at > func.now(),
            )
            .values(used_at=func.now())
            .returning(_COLUMNS.user_id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).scalar_one_or_none()

    async def invalidate(self, user_id: UUID, purpose: TokenPurpose) -> int:
        """Drop the user's unused tokens of one purpose; how many."""
        async with self._sessions.begin() as session:
            dropped = await session.execute(_unused(user_id, purpose).returning(_COLUMNS.id))
            return len(dropped.all())


def _unused(user_id: UUID, purpose: TokenPurpose) -> Delete:
    return delete(auth_tokens).where(
        _COLUMNS.user_id == user_id,
        _COLUMNS.purpose == purpose.value,
        _COLUMNS.used_at.is_(None),
    )
