"""What the auth services need from storage: one narrow protocol per table.

``storage.users.UserRepository`` and its siblings honour these in production; the in-memory
fakes in ``tests/fakes_accounts.py`` honour them in unit tests (one contract for both).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from storage.account_model import Role, TokenPurpose, User


class UserStore(Protocol):
    """Accounts."""

    async def create(
        self,
        email: str,
        password_hash: str,
        *,
        role: Role = Role.USER,
        verified: bool = False,
    ) -> User | None:
        """Add an account; None (nothing changed) when the email already has one."""
        ...

    async def by_email(self, email: str) -> User | None:
        """The account with this normalised email, or None."""
        ...

    async def by_id(self, user_id: UUID) -> User | None:
        """The account with this id, or None."""
        ...

    async def set_password(self, user_id: UUID, password_hash: str) -> bool:
        """Replace the password hash; whether the account exists."""
        ...

    async def mark_verified(self, user_id: UUID) -> bool:
        """Record that the address was verified (the first time only)."""
        ...

    async def set_role(self, user_id: UUID, role: Role) -> bool:
        """Give the account a role; whether it exists."""
        ...

    async def delete(self, user_id: UUID) -> bool:
        """Delete the account and what cascades from it."""
        ...

    async def emails(self, ids: Iterable[UUID]) -> dict[UUID, str]:
        """The emails of the accounts that exist among ``ids``."""
        ...


class SessionStore(Protocol):
    """Signed-in sessions, stored by the hash of their token."""

    async def create(
        self,
        token_hash: str,
        user_id: UUID,
        *,
        idle_seconds: int,
        absolute_seconds: int,
    ) -> None:
        """Store a new session with its two expiries."""
        ...

    async def resolve(self, token_hash: str, idle_seconds: int) -> User | None:
        """The account behind a live session, whose idle expiry moves forward; else None (an
        expired session is deleted)."""
        ...

    async def revoke(self, token_hash: str) -> bool:
        """End one session; whether it existed."""
        ...

    async def revoke_all(self, user_id: UUID, *, keep: str | None = None) -> int:
        """End every session of the user except the one hashed ``keep``; how many ended."""
        ...

    async def purge_expired(self) -> int:
        """Delete every expired session; how many."""
        ...


class TokenStore(Protocol):
    """Single-use emailed tokens, stored by hash."""

    async def issue(
        self,
        user_id: UUID,
        purpose: TokenPurpose,
        token_hash: str,
        ttl_seconds: int,
    ) -> None:
        """Store a token and drop the user's unused older ones of the same purpose."""
        ...

    async def consume(self, purpose: TokenPurpose, token_hash: str) -> UUID | None:
        """Use a valid token once; its account, or None when it cannot be used."""
        ...

    async def invalidate(self, user_id: UUID, purpose: TokenPurpose) -> int:
        """Drop the user's unused tokens of one purpose; how many."""
        ...


class AttemptStore(Protocol):
    """Failed sign-in and recovery attempts per key and window."""

    async def record_failure(self, key: str, window_seconds: int) -> int:
        """Count one failure; the failures in the key's current window."""
        ...

    async def retry_after(self, key: str, window_seconds: int, limit: int) -> int | None:
        """Seconds until the key may try again when it reached ``limit``; else None."""
        ...

    async def clear(self, key: str) -> None:
        """Forget the key's failures."""
        ...


@dataclass(frozen=True)
class Accounts:
    """The four account stores of one app."""

    users: UserStore
    sessions: SessionStore
    tokens: TokenStore
    attempts: AttemptStore
