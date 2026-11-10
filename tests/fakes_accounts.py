"""In-memory account stores and a recording mailer that honour the real contracts.

The stores follow the same rules as the PostgreSQL ones in ``storage/``: a unique email, hashed
session and token values, idle and absolute expiry, single-use tokens, and failure windows. A
``FakeClock`` lets a test move time.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from api.services.auth.mailer import Mail
from api.services.auth.stores import Accounts
from storage.account_model import Role, TokenPurpose, User


class FakeClock:
    """A clock a test can move."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        """Move time forward."""
        self.now += timedelta(seconds=seconds)


class InMemoryUsers:
    """The ``UserStore`` contract in process memory."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._users: dict[UUID, User] = {}
        self._count = 0  # ids are UUID(int=1), UUID(int=2), ... so tests can name an owner
        self.cascade: list[Callable[[UUID], None]] = []

    async def create(
        self,
        email: str,
        password_hash: str,
        *,
        role: Role = Role.USER,
        verified: bool = False,
    ) -> User | None:
        if await self.by_email(email) is not None:
            return None
        now = self._clock()
        self._count += 1
        user = User(
            UUID(int=self._count),
            email,
            password_hash,
            role,
            now if verified else None,
            now,
        )
        self._users[user.id] = user
        return user

    async def by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    def _change(self, user_id: UUID, **values: object) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        self._users[user_id] = replace(user, **values)  # type: ignore[arg-type]
        return True

    async def set_password(self, user_id: UUID, password_hash: str) -> bool:
        return self._change(user_id, password_hash=password_hash)

    async def mark_verified(self, user_id: UUID) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        return self._change(user_id, verified_at=user.verified_at or self._clock())

    async def set_role(self, user_id: UUID, role: Role) -> bool:
        return self._change(user_id, role=role)

    async def delete(self, user_id: UUID) -> bool:
        if self._users.pop(user_id, None) is None:
            return False
        for cleanup in self.cascade:
            cleanup(user_id)
        return True

    async def emails(self, ids: Iterable[UUID]) -> dict[UUID, str]:
        return {i: self._users[i].email for i in ids if i in self._users}


@dataclass
class _Session:
    user_id: UUID
    idle_expires_at: datetime
    absolute_expires_at: datetime


class InMemorySessions:
    """The ``SessionStore`` contract in process memory (keyed by the token hash)."""

    def __init__(self, users: InMemoryUsers, clock: Callable[[], datetime]) -> None:
        self._users = users
        self._clock = clock
        self.rows: dict[str, _Session] = {}
        users.cascade.append(lambda uid: self._drop_user(uid))

    def _drop_user(self, user_id: UUID) -> None:
        self.rows = {h: s for h, s in self.rows.items() if s.user_id != user_id}

    async def create(
        self,
        token_hash: str,
        user_id: UUID,
        *,
        idle_seconds: int,
        absolute_seconds: int,
    ) -> None:
        now = self._clock()
        self.rows[token_hash] = _Session(
            user_id,
            now + timedelta(seconds=idle_seconds),
            now + timedelta(seconds=absolute_seconds),
        )

    async def resolve(self, token_hash: str, idle_seconds: int) -> User | None:
        row = self.rows.get(token_hash)
        if row is None:
            return None
        now = self._clock()
        if row.idle_expires_at <= now or row.absolute_expires_at <= now:
            del self.rows[token_hash]
            return None
        row.idle_expires_at = min(now + timedelta(seconds=idle_seconds), row.absolute_expires_at)
        return await self._users.by_id(row.user_id)

    async def revoke(self, token_hash: str) -> bool:
        return self.rows.pop(token_hash, None) is not None

    async def revoke_all(self, user_id: UUID, *, keep: str | None = None) -> int:
        gone = [h for h, s in self.rows.items() if s.user_id == user_id and h != keep]
        for token_hash in gone:
            del self.rows[token_hash]
        return len(gone)

    async def purge_expired(self) -> int:
        now = self._clock()
        gone = [
            h
            for h, s in self.rows.items()
            if s.idle_expires_at <= now or s.absolute_expires_at <= now
        ]
        for token_hash in gone:
            del self.rows[token_hash]
        return len(gone)


@dataclass
class _Token:
    purpose: TokenPurpose
    user_id: UUID
    expires_at: datetime
    used: bool = False


class InMemoryTokens:
    """The ``TokenStore`` contract in process memory (keyed by the token hash)."""

    def __init__(self, users: InMemoryUsers, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.rows: dict[str, _Token] = {}
        users.cascade.append(lambda uid: self._drop_user(uid))

    def _drop_user(self, user_id: UUID) -> None:
        self.rows = {h: t for h, t in self.rows.items() if t.user_id != user_id}

    async def issue(
        self,
        user_id: UUID,
        purpose: TokenPurpose,
        token_hash: str,
        ttl_seconds: int,
    ) -> None:
        await self.invalidate(user_id, purpose)
        expires = self._clock() + timedelta(seconds=ttl_seconds)
        self.rows[token_hash] = _Token(purpose, user_id, expires)

    async def consume(self, purpose: TokenPurpose, token_hash: str) -> UUID | None:
        row = self.rows.get(token_hash)
        if row is None or row.purpose is not purpose or row.used or row.expires_at <= self._clock():
            return None
        row.used = True
        return row.user_id

    async def invalidate(self, user_id: UUID, purpose: TokenPurpose) -> int:
        gone = [
            h
            for h, t in self.rows.items()
            if t.user_id == user_id and t.purpose is purpose and not t.used
        ]
        for token_hash in gone:
            del self.rows[token_hash]
        return len(gone)


class InMemoryAttempts:
    """The ``AttemptStore`` contract in process memory."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._rows: dict[str, tuple[datetime, int]] = {}

    async def record_failure(self, key: str, window_seconds: int) -> int:
        now = self._clock()
        start, count = self._rows.get(key, (now, 0))
        if start <= now - timedelta(seconds=window_seconds):
            start, count = now, 0
        self._rows[key] = (start, count + 1)
        return count + 1

    async def retry_after(self, key: str, window_seconds: int, limit: int) -> int | None:
        row = self._rows.get(key)
        if row is None or row[1] < limit:
            return None
        remaining = (row[0] + timedelta(seconds=window_seconds) - self._clock()).total_seconds()
        return None if remaining <= 0 else max(1, math.ceil(remaining))

    async def clear(self, key: str) -> None:
        self._rows.pop(key, None)


def in_memory_accounts(clock: Callable[[], datetime]) -> Accounts:
    """The four stores, wired together (deleting a user deletes their sessions and tokens)."""
    users = InMemoryUsers(clock)
    return Accounts(
        users=users,
        sessions=InMemorySessions(users, clock),
        tokens=InMemoryTokens(users, clock),
        attempts=InMemoryAttempts(clock),
    )


class RecordingMailer:
    """A ``Mailer`` that keeps what it was asked to send (and can be made to fail)."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.sent: list[Mail] = []
        self._fail = fail

    async def send(self, mail: Mail) -> None:
        if self._fail is not None:
            raise self._fail
        self.sent.append(mail)
