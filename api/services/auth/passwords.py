"""Passwords: the length policy and Argon2id hashing with the configured cost.

Hashing and checking take tens of milliseconds, so they run in a worker thread. A sign-in for
an unknown email still pays for one verification (``verify_unknown``), so its timing does not
tell whether the account exists.
"""

from __future__ import annotations

import asyncio
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from config.auth import AuthSettings

TOO_SHORT = "Use at least {minimum} characters."
TOO_LONG = "Use at most {maximum} characters."
SAME_AS_EMAIL = "The password cannot be your email address."


class PasswordPolicyError(ValueError):
    """The password breaks the policy; ``str(error)`` is safe to show."""


class Passwords:
    """Checks and hashes passwords.

    Args:
        settings: The password length limits and Argon2id cost.
    """

    def __init__(self, settings: AuthSettings) -> None:
        cost = settings.argon2
        self._hasher = PasswordHasher(
            time_cost=cost.time_cost,
            memory_cost=cost.memory_cost_kib,
            parallelism=cost.parallelism,
        )
        self._minimum = settings.password_min_length
        self._maximum = settings.password_max_length
        self._dummy = self._hasher.hash(secrets.token_urlsafe(32))  # same cost as a real hash

    def check_length(self, password: str) -> None:
        """Raise unless the password is within the length limits.

        Raises:
            PasswordPolicyError: With the user-safe reason.
        """
        if len(password) < self._minimum:
            raise PasswordPolicyError(TOO_SHORT.format(minimum=self._minimum))
        if len(password) > self._maximum:
            raise PasswordPolicyError(TOO_LONG.format(maximum=self._maximum))

    def check_policy(self, password: str, email: str) -> None:
        """Raise unless the password is within the length limits and is not the email.

        No composition rule is imposed (NIST SP 800-63B).

        Raises:
            PasswordPolicyError: With the user-safe reason.
        """
        self.check_length(password)
        if password.casefold() == email.casefold():
            raise PasswordPolicyError(SAME_AS_EMAIL)

    async def hash(self, password: str) -> str:
        """The Argon2id hash of ``password`` (it embeds a random salt and its parameters)."""
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, stored: str, password: str) -> bool:
        """Whether ``password`` matches ``stored``; a malformed hash or password never matches."""
        if len(password) > self._maximum:  # the policy can never have accepted it
            return False
        return await asyncio.to_thread(self._matches, stored, password)

    def _matches(self, stored: str, password: str) -> bool:
        try:
            return self._hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False

    async def verify_unknown(self, password: str) -> None:
        """Spend one verification's time for an account that does not exist."""
        await self.verify(self._dummy, password)

    def needs_rehash(self, stored: str) -> bool:
        """Whether ``stored`` was made with other parameters than the configured ones."""
        return self._hasher.check_needs_rehash(stored)
