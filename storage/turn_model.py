"""A chat turn as stored: its status, why it stopped, how often it was resumed, and when.

A status changes only along ``queued -> running -> (interrupted | completed | failed)``,
``interrupted -> queued`` (a resume waits for a worker), ``interrupted -> running`` (a resume run
in place), ``queued -> failed`` (it could not be enqueued), ``interrupted -> failed`` (abandoned)
and ``interrupted -> completed`` (a resume found nothing left to run). Turns whose worker stopped
become ``interrupted``. The reason is an opaque code here; the program decodes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from storage.keys import ThreadKey

# Every turn id: 32 lowercase hex digits (a random UUID's hex); anything else names no turn.
TURN_ID_PATTERN = r"^[0-9a-f]{32}$"


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
        TurnStatus.QUEUED: frozenset({TurnStatus.INTERRUPTED}),
        TurnStatus.RUNNING: frozenset({TurnStatus.QUEUED, TurnStatus.INTERRUPTED}),
        TurnStatus.INTERRUPTED: frozenset(OPEN_STATUSES),
        TurnStatus.COMPLETED: frozenset({TurnStatus.RUNNING, TurnStatus.INTERRUPTED}),
        TurnStatus.FAILED: frozenset(
            {TurnStatus.QUEUED, TurnStatus.RUNNING, TurnStatus.INTERRUPTED},
        ),
    },
)


@dataclass(frozen=True)
class PlannedInput:
    """What a new turn sends the agent, recorded with the turn so a worker can read it (a task
    message carries ids only).

    Attributes:
        question: What the user typed, as recorded on the span.
        message: The message the agent receives (the question, or the answers to a request).
        note: The note on the user's answers for the agent; empty when there is none.
        counted: Whether the turn used one of the user's daily turns (only then is it given
            back when it stops before reaching the model).
    """

    question: str
    message: str
    note: str = ""
    counted: bool = False


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
        heartbeat_at: When its worker last reported it alive; None before it ran.
        cancel_requested: The user asked to stop it; its worker stops after the current step.
        planned: The input of a new turn; None for a turn recorded without one.
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
    heartbeat_at: datetime | None = None
    cancel_requested: bool = False
    planned: PlannedInput | None = None

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
