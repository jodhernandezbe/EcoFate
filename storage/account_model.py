"""Accounts as stored: users, their sessions and the purposes of single-use tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    """What an account may do: ``admin`` also sees the Monitoring view."""

    USER = "user"
    ADMIN = "admin"


class TokenPurpose(StrEnum):
    """What an emailed single-use token is for."""

    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105  # nosec B105  # a purpose name, not a secret  # pragma: allowlist secret


@dataclass(frozen=True)
class User:
    """One account (a copy; changes go through ``UserRepository``).

    Attributes:
        id: Random identifier; the only thing about the account that reaches spans.
        email: Normalised address (trimmed, domain lower-cased); unique.
        password_hash: Argon2id hash. Never leaves the storage and auth layers.
        role: ``user`` or ``admin``.
        verified_at: When the address was verified; None while unverified.
        created_at: When the account was created.
    """

    id: UUID
    email: str
    password_hash: str
    role: Role
    verified_at: datetime | None
    created_at: datetime

    @property
    def verified(self) -> bool:
        """Whether the email address was verified."""
        return self.verified_at is not None
