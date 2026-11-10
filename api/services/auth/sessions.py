"""Sessions: a random token in an ``HttpOnly`` cookie, kept server-side as its hash.

Signing in always starts a new session and ends the one the browser presented (so a session
id planted before sign-in is worthless). A request resolves the cookie to an account and moves
the idle expiry forward; the absolute expiry never moves.
"""

from __future__ import annotations

from typing import Literal, TypedDict
from uuid import UUID

from api.services.auth.stores import SessionStore
from api.services.auth.tokens import TokenHasher, new_token, plausible
from config.auth import AuthSettings
from storage.account_model import User


class CookieSettings(TypedDict):
    """Keyword arguments of ``Response.set_cookie`` for the session cookie."""

    key: str
    httponly: bool
    secure: bool
    samesite: Literal["lax"]
    path: str
    max_age: int


class SessionService:
    """Starts, resolves and ends sessions.

    Args:
        store: Where the session hashes are kept.
        hasher: Hashes a session token for storage and lookup.
        settings: Lifetimes and cookie flags.
    """

    def __init__(self, store: SessionStore, hasher: TokenHasher, settings: AuthSettings) -> None:
        self._store = store
        self._hasher = hasher
        self._settings = settings

    @property
    def cookie_name(self) -> str:
        """The session cookie's name."""
        return self._settings.cookie_name

    def cookie(self) -> CookieSettings:
        """The attributes of the session cookie (the token is passed as its value)."""
        return CookieSettings(
            key=self._settings.cookie_name,
            httponly=True,
            secure=self._settings.cookie_secure,
            samesite="lax",
            path="/",
            max_age=self._settings.session_absolute_seconds,
        )

    async def start(self, user_id: UUID, presented: str | None) -> str:
        """A new session for the user; the session the browser presented, if any, is ended."""
        if plausible(presented) and presented is not None:
            await self._store.revoke(self._hasher.digest(presented))
        token = new_token()
        await self._store.create(
            self._hasher.digest(token),
            user_id,
            idle_seconds=self._settings.session_idle_seconds,
            absolute_seconds=self._settings.session_absolute_seconds,
        )
        return token

    async def resolve(self, token: str | None) -> User | None:
        """The account behind a live session cookie, or None."""
        if token is None or not plausible(token):
            return None
        digest = self._hasher.digest(token)
        return await self._store.resolve(digest, self._settings.session_idle_seconds)

    async def end(self, token: str | None) -> None:
        """End the session the cookie names (nothing happens for an unknown one)."""
        if token is not None and plausible(token):
            await self._store.revoke(self._hasher.digest(token))

    async def end_all(self, user_id: UUID, keep: str | None = None) -> int:
        """End every session of the user, except the one whose cookie is ``keep``."""
        kept = self._hasher.digest(keep) if keep is not None and plausible(keep) else None
        return await self._store.revoke_all(user_id, keep=kept)
