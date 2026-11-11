"""Hand a recorded turn to the background worker and say how its stream is read.

The chat routes record the turn as ``queued`` (with its input), then ``submit`` writes the
stream's first record (the queue position) and enqueues the turn by id. When Redis cannot be
reached the turn is not left ``queued``: a new turn fails (a counted one is given back), a
resumed one is interrupted again, the thread is released, and the route answers 503.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

from redis.exceptions import RedisError

from api.services.agent_runner import RelayTiming
from api.services.threads import ThreadStore
from app.task_queue import EnqueueError, TurnEnqueuer, TurnJob
from app.telemetry import TurnSegment, enqueue_span
from app.turns import FailureReason
from app.turns.bus import TurnEventBus, turn_stream
from app.turns.codec import TurnQueued, encode
from app.turns.recording import QUEUED_SEQ, BackgroundSettings
from config.telemetry import TelemetrySettings
from storage.errors import DATABASE_ERRORS
from storage.turn_model import Turn, TurnStatus, TurnTransitionError

logger = logging.getLogger(__name__)
UNAVAILABLE = "The assessment service is not available right now. Try again in a moment."
EVENTS_EXPIRED = "This run's live progress is no longer available. Reload the thread to see it."
Refund = Callable[[UUID, str], Awaitable[bool]]
_BROKER_ERRORS = (EnqueueError, RedisError, OSError, TimeoutError)


class QueueUnavailableError(Exception):
    """The turn could not be enqueued (answered 503 with ``UNAVAILABLE``)."""


@dataclass
class QueueSetup:
    """What the app keeps for the queue (built at start-up, injected in tests).

    Attributes:
        bus: The turns' event streams.
        enqueuer: Hands turns to the worker; None runs each turn in this process
            (``[worker].eager``, tests) through the same job.
        timing: How a reader waits.
        background: Timing of a turn run in this process (and the stream lifetimes).
        running: Turns running in this process, kept until they end.
    """

    bus: TurnEventBus
    enqueuer: TurnEnqueuer | None
    timing: RelayTiming
    background: BackgroundSettings
    running: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])


@dataclass(frozen=True)
class TurnQueue:
    """The queue of one request: the streams, the enqueuer and the timing."""

    bus: TurnEventBus
    enqueuer: TurnEnqueuer
    timing: RelayTiming
    background: BackgroundSettings


async def submit(
    turn: Turn,
    queue: TurnQueue,
    threads: ThreadStore,
    refund: Refund | None,
    telemetry: TelemetrySettings | None = None,
) -> None:
    """Write the queued record (with the queue position) and enqueue the turn, inside the
    enqueue span whose trace the worker continues.

    Raises:
        QueueUnavailableError: Redis could not be reached; the turn and thread were cleaned up.
    """
    segment = TurnSegment(turn.id, turn.resume_count)
    try:
        with enqueue_span(telemetry, turn.thread_id, segment, str(turn.owner_id)):
            await _enqueue(turn, queue, threads)
    except _BROKER_ERRORS as error:
        logger.warning("Turn %s could not be enqueued: %s", turn.id, type(error).__name__)
        await _not_queued(turn, threads, refund)
        raise QueueUnavailableError(UNAVAILABLE) from None


async def _enqueue(turn: Turn, queue: TurnQueue, threads: ThreadStore) -> None:
    position = await threads.turns.queue_position(turn.id)
    record = encode(TurnQueued(position))
    stream = turn_stream(turn.id, turn.resume_count)
    await queue.bus.publish(stream, QUEUED_SEQ, record, queue.background.running_ttl_seconds)
    await queue.enqueuer.enqueue(TurnJob(turn.id, turn.owner_id))


async def _not_queued(turn: Turn, threads: ThreadStore, refund: Refund | None) -> None:
    """A new turn fails (and is given back); a resumed one is interrupted again. Each step is
    only logged when it cannot be done."""
    resumed = turn.resume_count > 0
    target = TurnStatus.INTERRUPTED if resumed else TurnStatus.FAILED
    reason = FailureReason.WORKER_LOST if resumed else FailureReason.UNEXPECTED
    try:
        await threads.turns.move(turn.owner_id, turn.id, target, reason)
        if refund is not None and not resumed:
            await refund(turn.owner_id, turn.id)
    except (TurnTransitionError, *DATABASE_ERRORS) as error:
        logger.warning("Turn %s not cleaned up: %s", turn.id, type(error).__name__)
    await threads.release(turn.key)
