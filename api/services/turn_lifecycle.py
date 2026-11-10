"""The life of a turn record around the thread's lease: start, resume, abandon, report.

The caller holds the thread's lease (``ThreadStore.claim``) before starting or resuming, so a
turn still open on the thread is stale (its process stopped) and becomes
``interrupted/worker_lost``. A refused resume raises ``TurnRefused`` with a fixed message.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from api.schemas.chat import InterruptionReason, TurnInterruption
from api.services.provider_errors import interruption_message, message_for
from api.services.threads import ThreadStore
from app.turns import FailureReason, KeysUnavailableError, resumable
from storage.keys import ThreadKey
from storage.turn_model import Turn, TurnStatus

BUSY = "A turn is already running for this thread."
NOTHING_TO_RESUME = "This thread has no interrupted turn to resume."
RESUME_CAP = "This turn has been resumed the maximum number of times. Send a new message instead."
_CONFLICT = 409


class TurnRefused(Exception):
    """A turn cannot start or resume; ``detail`` is a fixed message safe to show."""

    def __init__(self, detail: str, status: int = _CONFLICT) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def resumable_reason(turn: Turn | None) -> FailureReason | None:
    """The reason an interrupted turn stopped, when it is a known resumable one; else None.

    The stored reason is untrusted: an unknown code reads as not resumable.
    """
    if turn is None or turn.status is not TurnStatus.INTERRUPTED or turn.reason is None:
        return None
    try:
        reason = FailureReason(turn.reason)
    except ValueError:
        return None
    return reason if resumable(reason) else None


def can_resume(turn: Turn, max_resumes: int) -> bool:
    """Whether the interrupted turn may be resumed once more."""
    return resumable_reason(turn) is not None and turn.resume_count < max_resumes


def interruption(turn: Turn | None, max_resumes: int) -> TurnInterruption | None:
    """How an interrupted latest turn is reported (reason, resumable, message); else None."""
    reason = resumable_reason(turn)
    if turn is None or reason is None:
        return None
    again = turn.resume_count < max_resumes
    return TurnInterruption(
        reason=cast(InterruptionReason, reason.value),
        resumable=again,
        message=interruption_message(reason, resumable=again),
    )


async def start_turn(threads: ThreadStore, key: ThreadKey) -> Turn:
    """Record a new message's turn; an interrupted latest turn is abandoned first.

    Its unanswered tool calls are closed by the runner before the new message runs.

    Raises:
        TurnRefused: Another turn of the thread is open (409).
    """
    await threads.turns.interrupt_open(key, FailureReason.WORKER_LOST)
    latest = await threads.turns.latest(key)
    if latest is not None and latest.status is TurnStatus.INTERRUPTED:
        await threads.turns.move(
            key.owner_id,
            latest.id,
            TurnStatus.FAILED,
            FailureReason.SUPERSEDED,
        )
    turn = await threads.turns.begin(key)
    if turn is None:
        raise TurnRefused(BUSY)
    return turn


async def resume_turn_record(
    threads: ThreadStore,
    key: ThreadKey,
    max_resumes: int,
    pending_steps: Callable[[], Awaitable[tuple[str, ...]]],
) -> Turn:
    """Move the thread's interrupted turn back to running, after checking it can resume.

    ``pending_steps`` reports what the checkpoint would run next. A refusal changes nothing,
    except that a turn whose checkpoint has nothing left to run is marked completed.

    Raises:
        TurnRefused: Nothing to resume, the cap is reached, no key, or the thread is busy.
    """
    await threads.turns.interrupt_open(key, FailureReason.WORKER_LOST)
    latest = await threads.turns.latest(key)
    if latest is None or resumable_reason(latest) is None:
        raise TurnRefused(NOTHING_TO_RESUME)
    if latest.resume_count >= max_resumes:
        raise TurnRefused(RESUME_CAP)
    await _require_next_step(threads, latest, pending_steps)
    resumed = await threads.turns.resume(key.owner_id, latest.id, max_resumes)
    if resumed is None:
        raise TurnRefused(BUSY)
    return resumed


async def _require_next_step(
    threads: ThreadStore,
    turn: Turn,
    pending_steps: Callable[[], Awaitable[tuple[str, ...]]],
) -> None:
    try:
        steps = await pending_steps()
    except KeysUnavailableError as error:
        raise TurnRefused(message_for(error.reason)) from None
    if not steps:
        await threads.turns.move(turn.owner_id, turn.id, TurnStatus.COMPLETED)
        raise TurnRefused(NOTHING_TO_RESUME)
