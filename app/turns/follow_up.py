"""The automatic follow-up turn of a background job: recorded when the job ends, run at most once.

When a job ends (succeeded, failed or interrupted; one the user cancelled needs no explanation),
``FollowUps.job_ended`` records one turn of the job's thread, ``waiting``, whose input is a fixed
message ("Background job {id} ({tool}) ended: {status}") and whose id is the job's: the unique
index on ``turns.job_id`` makes a second recording (a repeated callback, a recovery sweep after
the runner) find nothing to do. The turn starts only when the thread is free: ``release_next`` takes
the thread's lease, moves the oldest waiting turn to ``queued`` and enqueues it. It is called in
exactly two places: right after the job is recorded (the thread may be idle), and by the finisher
of every turn once it has released the thread (the thread was busy when the job ended).

The job's result reaches the model as a tool result (``follow_up_messages``): a call of the job's
tool and its result, content and artifact, so it is handled as untrusted tool output, never as
instructions, and the workspace fills through the usual path from the stored tool messages.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall, ToolMessage

from app.task_queue import EnqueueError, TurnEnqueuer, TurnJob
from app.turns.bus import TurnEventBus, turn_stream
from app.turns.codec import TurnQueued, encode
from app.turns.failures import FailureReason
from app.turns.recording import QUEUED_SEQ
from storage.errors import DATABASE_ERRORS
from storage.job_model import Job, JobStatus
from storage.keys import ThreadKey
from storage.turn_model import PlannedInput, Turn, TurnStatus, TurnTransitionError

logger = logging.getLogger("app.turns.follow_up")
AUTOMATIC = "automatic_job"  # the marker on the notice message (hidden from the chat)
# Statuses whose end the user is told about by a follow-up turn.
EXPLAINED = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.INTERRUPTED)


class FollowUpTurns(Protocol):
    """The turn records a follow-up reads and moves (``storage.turns.TurnRepository``)."""

    async def begin_follow_up(
        self,
        key: ThreadKey,
        job_id: str,
        planned: PlannedInput,
    ) -> Turn | None: ...

    async def next_waiting(self, key: ThreadKey) -> Turn | None: ...

    async def activate(self, owner_id: UUID, turn_id: str) -> Turn | None: ...

    async def queue_position(self, turn_id: str) -> int: ...

    async def move(
        self,
        owner_id: UUID,
        turn_id: str,
        target: TurnStatus,
        reason: str | None = None,
    ) -> Turn: ...


class FollowUpThreads(Protocol):
    """The thread lease and turn records (``storage.threads.PostgresThreadStore``)."""

    @property
    def turns(self) -> FollowUpTurns: ...

    async def claim(self, key: ThreadKey) -> bool: ...

    async def release(self, key: ThreadKey) -> None: ...


def notice(job: Job) -> str:
    """The fixed message that tells the agent a job ended (no result, no reason text)."""
    return f"Background job {job.id} ({job.tool}) ended: {job.status.value}"


def _call_id(job: Job) -> str:
    return f"job_{job.id}"


def _result_text(job: Job) -> str:
    """What the job's tool call 'returned': its result, or its status and fixed reason."""
    if job.status is JobStatus.SUCCEEDED and job.result_content is not None:
        return json.dumps(job.result_content)
    return json.dumps({"job_id": job.id, "status": job.status.value, "reason": job.failure_reason})


def tool_exchange(job: Job) -> tuple[AIMessage, ToolMessage]:
    """The job as a tool call and its result: the call's arguments and the job's result and
    artifact. A job that did not succeed is an error result (the workspace ignores it)."""
    stored = job.input.get("arguments")
    arguments = dict(cast(Mapping[str, object], stored)) if isinstance(stored, dict) else {}
    call = ToolCall(name=job.tool, args=arguments, id=_call_id(job), type="tool_call")
    succeeded = job.status is JobStatus.SUCCEEDED and job.result_artifact is not None
    result = ToolMessage(
        content=_result_text(job),
        tool_call_id=_call_id(job),
        name=job.tool,
        artifact=dict(job.result_artifact) if succeeded and job.result_artifact else None,
        status="success" if succeeded else "error",
    )
    return AIMessage(content="", tool_calls=[call]), result


def follow_up_messages(job: Job) -> list[AnyMessage]:
    """The turn's input: the notice, then the job's tool call and result (untrusted tool output)."""
    marker = {AUTOMATIC: job.id}
    first = HumanMessage(content=notice(job), additional_kwargs=marker)
    return [first, *tool_exchange(job)]


@dataclass(frozen=True)
class FollowUps:
    """Records and starts the follow-up turns of ended jobs.

    Attributes:
        threads: The thread lease and turn records.
        bus: The turn streams (the queued record of a follow-up is written here).
        enqueuer: Hands a queued turn to the chat worker.
        queued_ttl_seconds: How long a queued turn's stream is kept.
    """

    threads: FollowUpThreads
    bus: TurnEventBus
    enqueuer: TurnEnqueuer
    queued_ttl_seconds: int

    async def job_ended(self, job: Job) -> None:
        """Record the job's follow-up (once) and start it when the thread is free."""
        if job.status not in EXPLAINED:
            return
        planned = PlannedInput(notice(job), notice(job), "", counted=False)
        turn = await self.threads.turns.begin_follow_up(job.key, job.id, planned)
        if turn is None:
            logger.info("Job %s already has a follow-up", job.id)
            return
        await self.release_next(job.key)

    async def release_next(self, key: ThreadKey) -> None:
        """Start the thread's oldest waiting follow-up when the thread is free (safe to call
        any time, from any process: only one caller wins the lease and the activation)."""
        if not await self.threads.claim(key):
            return
        turn = await self._activated(key)
        if turn is None:
            await self.threads.release(key)
            return
        await self._enqueue(turn)

    async def _activated(self, key: ThreadKey) -> Turn | None:
        waiting = await self.threads.turns.next_waiting(key)
        return (
            None if waiting is None else await self.threads.turns.activate(key.owner_id, waiting.id)
        )

    async def _enqueue(self, turn: Turn) -> None:
        """Write the turn's queued record and enqueue it; a queue that cannot be reached fails
        the turn and frees the thread (logged by class only)."""
        try:
            position = await self.threads.turns.queue_position(turn.id)
            stream = turn_stream(turn.id, turn.resume_count)
            await self.bus.publish(
                stream,
                QUEUED_SEQ,
                encode(TurnQueued(position)),
                self.queued_ttl_seconds,
            )
            await self.enqueuer.enqueue(TurnJob(turn.id, turn.owner_id))
        except (EnqueueError, OSError, TimeoutError) as error:
            logger.warning("Follow-up %s not enqueued: %s", turn.id, type(error).__name__)
            await self._abandon(turn)

    async def _abandon(self, turn: Turn) -> None:
        reason = FailureReason.UNEXPECTED
        try:
            await self.threads.turns.move(turn.owner_id, turn.id, TurnStatus.FAILED, reason)
        except (TurnTransitionError, *DATABASE_ERRORS) as error:
            logger.warning("Follow-up %s not closed: %s", turn.id, type(error).__name__)
        await self.threads.release(turn.key)
