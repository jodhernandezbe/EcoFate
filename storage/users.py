"""``UserRepository``: accounts in PostgreSQL. Each call is one transaction.

Rows are untrusted on read (``codec.user_from_row``). The password hash only ever travels
inside ``User``.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storage import codec
from storage.account_model import Role, User
from storage.tables import users

Sessions = async_sessionmaker[AsyncSession]


class UserRepository:
    """Creates, reads and changes accounts.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(
        self,
        email: str,
        password_hash: str,
        *,
        role: Role = Role.USER,
        verified: bool = False,
    ) -> User | None:
        """Add an account; None (nothing changed) when the email already has one."""
        statement = (
            pg_insert(users)
            .values(
                id=uuid4(),
                email=email,
                password_hash=password_hash,
                role=role.value,
                verified_at=func.now() if verified else None,
            )
            .on_conflict_do_nothing(index_elements=[users.c.email])
            .returning(*users.c)
        )
        async with self._sessions.begin() as session:
            return codec.user_from_row((await session.execute(statement)).mappings().first())

    async def by_email(self, email: str) -> User | None:
        """The account with this (normalised) email, or None."""
        return await self._one(users.c.email == email)

    async def by_id(self, user_id: UUID) -> User | None:
        """The account with this id, or None."""
        return await self._one(users.c.id == user_id)

    async def _one(self, where: ColumnElement[bool]) -> User | None:
        async with self._sessions() as session:
            row = (await session.execute(select(users).where(where))).mappings().first()
        return codec.user_from_row(row)

    async def set_password(self, user_id: UUID, password_hash: str) -> bool:
        """Replace the password hash; whether the account exists."""
        return await self._change(user_id, password_hash=password_hash)

    async def mark_verified(self, user_id: UUID) -> bool:
        """Record that the address was verified (the first time only); whether it exists."""
        return await self._change(
            user_id,
            verified_at=func.coalesce(users.c.verified_at, func.now()),
        )

    async def set_role(self, user_id: UUID, role: Role) -> bool:
        """Give the account a role; whether it exists."""
        return await self._change(user_id, role=role.value)

    async def _change(self, user_id: UUID, **values: object) -> bool:
        statement = (
            update(users).where(users.c.id == user_id).values(**values).returning(users.c.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def delete(self, user_id: UUID) -> bool:
        """Delete the account; its sessions, tokens and threads go with it (cascade)."""
        statement = delete(users).where(users.c.id == user_id).returning(users.c.id)
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def emails(self, ids: Iterable[UUID]) -> dict[UUID, str]:
        """The emails of the accounts that exist among ``ids`` (a deleted account is absent)."""
        wanted = list(ids)
        if not wanted:
            return {}
        statement = select(users.c.id, users.c.email).where(users.c.id.in_(wanted))
        async with self._sessions() as session:
            return {row.id: row.email for row in await session.execute(statement)}
