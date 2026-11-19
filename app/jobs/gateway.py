"""The job system as the tools see it (``tools.jobs.port.JobPort``): record, queue, report.

``submit`` records the job (atomically under the owner's cap of open jobs), tells the thread's
readers (``job.queued``) and hands it to the tools worker by id; a queue that cannot be reached
leaves no queued job behind. ``status`` reports the owner's jobs of one thread, never a result:
the follow-up turn is what explains it. The owner and thread are arguments of these calls only
because the tool takes them from the run's configuration; nothing here reads a tool's arguments.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.jobs.failures import JobFailure
from app.task_queue import EnqueueError, ToolJob, ToolJobEnqueuer
from app.turns.thread_bus import ThreadEventBus, job_record, publish_quietly
from storage.errors import DATABASE_ERRORS
from storage.job_model import Job, JobStatus, JobStore
from storage.keys import ThreadKey
from tools.jobs.port import JobUnavailableError
from tools.schemas import JobStatusEntry, SubmittedJob

logger = logging.getLogger("app.jobs")
_OUTCOMES = {
    JobStatus.SUCCEEDED: "finished; its results arrive in the follow-up message",
    JobStatus.FAILED: "failed; nothing was assessed",
    JobStatus.CANCELLED: "cancelled by the user",
    JobStatus.INTERRUPTED: "stopped early because its worker was lost; it was not re-run",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class JobGateway:
    """Records, queues and reports background jobs for the tools of a turn.

    Attributes:
        store: The jobs table.
        enqueuer: Hands a queued job to a tools worker (ids only).
        max_open: Queued plus running jobs one user may have (``[worker].max_open_jobs_per_user``).
        thread_bus: Where ``job.queued`` is published; None publishes nothing.
        event_ttl_seconds: How long a thread's stream is kept after its last event.
        clock: The time source (a test fixes it).
    """

    store: JobStore
    enqueuer: ToolJobEnqueuer
    max_open: int
    thread_bus: ThreadEventBus | None = None
    event_ttl_seconds: int = 3600
    clock: Callable[[], datetime] = _utc_now

    async def submit(
        self,
        owner_id: UUID,
        thread_id: str,
        tool: str,
        job_input: Mapping[str, object],
    ) -> SubmittedJob | None:
        """Record and queue a job; None (nothing recorded) over the owner's cap.

        Raises:
            JobUnavailableError: The job could not be recorded or queued (nothing stays queued).
        """
        key = ThreadKey(owner_id, thread_id)
        try:
            job = await self.store.create(key, tool, job_input, self.max_open)
            if job is None:
                return None
            position = await self.store.queue_position(owner_id, job.id)
        except DATABASE_ERRORS as error:
            logger.warning("Job not recorded: %s", type(error).__name__)
            raise JobUnavailableError from None
        await self._publish(job)
        await self._enqueue(job)
        return SubmittedJob(job_id=job.id, status="queued", position=position)

    async def _publish(self, job: Job) -> None:
        record = job_record("job.queued", job)
        await publish_quietly(self.thread_bus, job.key, record, self.event_ttl_seconds)

    async def _enqueue(self, job: Job) -> None:
        """Hand the job to the queue; when that fails the job is interrupted (it would hold the
        owner's cap with no task behind it) and the readers are told."""
        try:
            await self.enqueuer.enqueue(ToolJob(job.id, job.owner_id))
        except (EnqueueError, OSError, TimeoutError) as error:
            logger.warning("Job %s not enqueued: %s", job.id, type(error).__name__)
            ended = await self.store.interrupt(job.owner_id, job.id, JobFailure.NOT_STARTED)
            if ended is not None:
                record = job_record("job.ended", ended)
                await publish_quietly(self.thread_bus, ended.key, record, self.event_ttl_seconds)
            raise JobUnavailableError from None

    async def status(
        self,
        owner_id: UUID,
        thread_id: str,
        job_id: str | None,
    ) -> list[JobStatusEntry]:
        """The owner's jobs of the thread (just ``job_id`` when given), oldest first."""
        try:
            jobs = await self.store.for_thread(ThreadKey(owner_id, thread_id))
            wanted = [j for j in jobs if job_id is None or j.id == job_id]
            return [await self._entry(job) for job in wanted]
        except DATABASE_ERRORS as error:
            logger.warning("Job status not read: %s", type(error).__name__)
            raise JobUnavailableError from None

    async def _entry(self, job: Job) -> JobStatusEntry:
        now = self.clock()
        entry = JobStatusEntry(
            job_id=job.id,
            tool=job.tool,
            status=job.status.value,
            elapsed_seconds=round(elapsed_seconds(job, now), 1),
        )
        if job.status is JobStatus.QUEUED:
            entry["position"] = await self.store.queue_position(job.owner_id, job.id)
        if job.status in _OUTCOMES:
            entry["outcome"] = _OUTCOMES[job.status]
        return entry


def elapsed_seconds(job: Job, now: datetime) -> float:
    """Seconds waiting while queued, running while running, and the run's length once ended."""
    if job.status is JobStatus.QUEUED:
        return max((now - job.queued_at).total_seconds(), 0.0)
    began = job.started_at or job.queued_at
    return max(((job.ended_at or now) - began).total_seconds(), 0.0)
