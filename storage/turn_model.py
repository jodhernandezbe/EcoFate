"""A chat turn as stored: its status, why it stopped, how often it was resumed, and when.

A status changes only along ``queued -> running -> (interrupted | completed | failed)``,
``interrupted -> running`` (a resume), ``interrupted -> failed`` (abandoned) and
``interrupted -> completed`` (a resume found nothing left to run). Turns left ``queued`` or
``running`` by a stopped process become ``interrupted``. The reason is an opaque code here; the
web program decodes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from storage.keys import ThreadKey


class TurnStatus(StrEnum):
    """Where a turn is in its life."""

    QUEUED = "queued"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


# The statuses of a turn that holds its thread; at most one per thread (a partial unique index).
OPEN_STATUSES = (TurnStatus.QUEUED, TurnStatus.RUNNING)
# The statuses that carry a reason (and only these).
REASONED_STATUSES = (TurnStatus.INTERRUPTED, TurnStatus.FAILED)
# Target status -> the statuses a turn may move to it from.
ALLOWED_FROM = MappingProxyType(
    {
        TurnStatus.RUNNING: frozenset({TurnStatus.QUEUED, TurnStatus.INTERRUPTED}),
        TurnStatus.INTERRUPTED: frozenset(OPEN_STATUSES),
        TurnStatus.COMPLETED: frozenset({TurnStatus.RUNNING, TurnStatus.INTERRUPTED}),
        TurnStatus.FAILED: frozenset({TurnStatus.RUNNING, TurnStatus.INTERRUPTED}),
    },
)


class TurnTransitionError(Exception):
    """A turn was asked to move to a status it cannot reach from where it is (nothing changed)."""


@dataclass(frozen=True)
class Turn:
    """One stored turn (a copy; changing the turn goes through its store).

    Attributes:
        id: The turn's id (also the ``turn_id`` of its stream events).
        owner_id: The user whose turn it is.
        thread_id: The conversation it belongs to (one of that user's).
        status: Where it is in its life.
        reason: Why it was interrupted or failed; None otherwise.
        resume_count: How many times it was resumed (each resume counts, even one that stopped).
        created_at: When it was recorded.
        started_at: When it first ran; None while queued.
        updated_at: When its status last changed.
        finished_at: When it completed or failed; None before.
    """

    id: str
    owner_id: UUID
    thread_id: str
    status: TurnStatus
    reason: str | None
    resume_count: int
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    finished_at: datetime | None

    @property
    def key(self) -> ThreadKey:
        """The thread the turn belongs to, with its owner."""
        return ThreadKey(self.owner_id, self.thread_id)


def check_transition(turn_id: str, current: TurnStatus, target: TurnStatus) -> None:
    """Raise unless a turn in ``current`` may move to ``target``.

    Raises:
        TurnTransitionError: The move is not allowed; the message names both statuses.
    """
    if current not in ALLOWED_FROM.get(target, frozenset()):
        raise TurnTransitionError(f"turn {turn_id} cannot move from {current} to {target}")
