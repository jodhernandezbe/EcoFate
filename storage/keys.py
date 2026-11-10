"""``ThreadKey``: who owns a thread and which one it is. The unit every thread lookup takes.

A thread id is chosen by the browser, so on its own it names nothing: two users may pick the
same one. Every storage operation on a thread artefact is therefore given the pair, and puts the
owner in its ``WHERE``, so a lookup can only ever reach the caller's own rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ThreadKey:
    """A thread of one user.

    Attributes:
        owner_id: The signed-in user's id, taken from the session and never from a request body.
        thread_id: The id the browser chose for the thread (``THREAD_ID_PATTERN``).
    """

    owner_id: UUID
    thread_id: str

    @property
    def checkpoint_id(self) -> str:
        """The checkpointer's thread key; owner-scoped so two users never share a checkpoint."""
        return f"{self.owner_id}:{self.thread_id}"
