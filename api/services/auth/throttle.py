"""Limiting failed sign-in and recovery attempts per account and per client address.

Counting lives in storage (an atomic upsert per key); this module names the keys and decides
who the client is. ``X-Forwarded-For`` is believed only as far as the configured number of
trusted proxies: with none, a client cannot choose its own address by sending the header.
"""

from __future__ import annotations

from api.services.auth.stores import AttemptStore
from config.auth import ThrottleSettings

_MAX_KEY_PART = 254


def client_address(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """The address the request really came from.

    With ``trusted_hops`` proxies in front, each appended the address it saw, so the client is
    the entry ``trusted_hops`` from the right; earlier entries are whatever the client claimed.
    Without trusted proxies, or when the header is missing or too short, the socket peer is it.
    """
    if trusted_hops > 0 and forwarded_for:
        entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
        if len(entries) >= trusted_hops:
            return entries[-trusted_hops][:_MAX_KEY_PART]
    return (peer or "unknown")[:_MAX_KEY_PART]


def attempt_keys(scope: str, email: str | None, address: str) -> list[str]:
    """The counters one attempt is counted on: the account (when named) and the address.

    ``scope`` keeps sign-in failures and recovery requests on separate counters.
    """
    keys = [f"{scope}-ip:{address}"]
    if email:
        keys.append(email_key(scope, email))
    return keys


def email_key(scope: str, email: str) -> str:
    """The counter of one account within a scope."""
    return f"{scope}-email:{email.strip().casefold()[:_MAX_KEY_PART]}"


class Throttle:
    """Counts failures and answers whether a key may try.

    Args:
        store: Where the counters are kept.
        settings: The attempts allowed per window, and the window.
    """

    def __init__(self, store: AttemptStore, settings: ThrottleSettings) -> None:
        self._store = store
        self._settings = settings

    async def retry_after(self, keys: list[str]) -> int | None:
        """Seconds to wait when any key reached the limit; None when all may try."""
        limit, window = self._settings.attempts, self._settings.window_seconds
        waits = [await self._store.retry_after(key, window, limit) for key in keys]
        known = [wait for wait in waits if wait is not None]
        return max(known) if known else None

    async def fail(self, keys: list[str]) -> None:
        """Count one failed (or recovery) attempt on every key."""
        for key in keys:
            await self._store.record_failure(key, self._settings.window_seconds)

    async def forgive(self, keys: list[str]) -> None:
        """Forget the failures of the keys (after a successful sign-in)."""
        for key in keys:
            await self._store.clear(key)
