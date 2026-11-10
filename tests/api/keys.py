"""One owner for the service tests that work on the stores directly (no signed-in client)."""

from __future__ import annotations

from uuid import UUID

from storage.keys import ThreadKey

# The ids the in-memory account store gives its first two accounts: the default signed-in test
# user is OWNER, so a route test and a service test name the same threads.
OWNER = UUID(int=1)
OTHER_OWNER = UUID(int=2)


def owned(thread_id: str, owner_id: UUID = OWNER) -> ThreadKey:
    """The key of ``thread_id`` for ``owner_id`` (``OWNER`` by default)."""
    return ThreadKey(owner_id, thread_id)
