"""Random secrets and single-use tokens.

A session or emailed token is 256 random bits. Only its keyed hash (HMAC-SHA256 with the
session secret as the key) is ever stored or compared, so a copy of the database is neither a
cookie nor a link, and the hash of a hash is not a valid token.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from uuid import UUID

from api.services.auth.stores import TokenStore
from config.auth import AuthSettings
from storage.account_model import TokenPurpose

_MIN_SECRET_BYTES = 32
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


class SecretSetupError(RuntimeError):
    """The session secret is missing or too short; the message names the variable only."""


def new_token() -> str:
    """A fresh random token, safe in a cookie, a URL fragment and a request body."""
    return secrets.token_urlsafe(32)


def load_session_secret(environ: Mapping[str, str], settings: AuthSettings) -> bytes:
    """The session secret from the environment variable named in the settings.

    Raises:
        SecretSetupError: The variable is unset or holds fewer than 32 bytes (the message
            names the variable, never its value).
    """
    name = settings.session_secret_env_var
    value = environ.get(name, "").strip().encode()
    if len(value) < _MIN_SECRET_BYTES:
        raise SecretSetupError(
            f"Set {name} to a random secret of at least {_MIN_SECRET_BYTES} characters "
            "(see .env.example) before starting the web program.",
        )
    return value


class TokenHasher:
    """Keyed hash of tokens.

    Args:
        secret: The session secret (at least 32 bytes).
    """

    def __init__(self, secret: bytes) -> None:
        if len(secret) < _MIN_SECRET_BYTES:
            raise SecretSetupError("The session secret is too short.")
        self._secret = secret

    def digest(self, token: str) -> str:
        """The hash that is stored in place of ``token``."""
        return hmac.new(self._secret, token.encode(), hashlib.sha256).hexdigest()


def plausible(token: str | None) -> bool:
    """Whether ``token`` has the shape of one of ours (cheap check before touching storage)."""
    return token is not None and _TOKEN_SHAPE.fullmatch(token) is not None


class TokenService:
    """Issues and consumes single-use emailed tokens.

    Args:
        store: Where the token hashes are kept.
        hasher: Hashes a token for storage and lookup.
        settings: The token lifetimes.
    """

    def __init__(self, store: TokenStore, hasher: TokenHasher, settings: AuthSettings) -> None:
        self._store = store
        self._hasher = hasher
        self._lifetimes = {
            TokenPurpose.VERIFY_EMAIL: settings.verification_token_hours * _SECONDS_PER_HOUR,
            TokenPurpose.RESET_PASSWORD: settings.reset_token_minutes * _SECONDS_PER_MINUTE,
        }

    async def issue(self, user_id: UUID, purpose: TokenPurpose) -> str:
        """A new token for the user; it replaces their unused older ones of this purpose."""
        token = new_token()
        digest = self._hasher.digest(token)
        await self._store.issue(user_id, purpose, digest, self._lifetimes[purpose])
        return token

    async def consume(self, purpose: TokenPurpose, token: str) -> UUID | None:
        """Use a token once: its account, or None when it is unknown, expired or used."""
        if not plausible(token):
            return None
        return await self._store.consume(purpose, self._hasher.digest(token))

    async def invalidate(self, user_id: UUID, purpose: TokenPurpose) -> None:
        """Drop the user's unused tokens of one purpose."""
        await self._store.invalidate(user_id, purpose)
