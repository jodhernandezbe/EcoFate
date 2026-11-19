"""What a job's start and end tell the rest of the program: the thread's readers and the follow-up.

``JobLifecycle`` is wired as ``JobServices.on_job_started`` and ``on_job_ended`` (and the recovery
sweep's callback), so every way a job can end (the runner, a lost worker, a swept queue) publishes
``job.ended`` and records the job's follow-up turn the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.turns.thread_bus import ThreadEventBus, job_record, publish_quietly
from storage.job_model import Job


class JobFollowUp(Protocol):
    """Records and starts a job's follow-up turn (``app.turns.follow_up.FollowUps``)."""

    async def job_ended(self, job: Job) -> None: ...


@dataclass(frozen=True)
class JobLifecycle:
    """The callbacks of a job's life.

    Attributes:
        thread_bus: Where ``job.running`` and ``job.ended`` are published; None publishes none.
        event_ttl_seconds: How long a thread's stream is kept after its last event.
        follow_ups: Records and starts the follow-up turn when the job ends; None records none.
    """

    thread_bus: ThreadEventBus | None
    event_ttl_seconds: int
    follow_ups: JobFollowUp | None

    async def started(self, job: Job) -> None:
        """A worker claimed the job."""
        record = job_record("job.running", job)
        await publish_quietly(self.thread_bus, job.key, record, self.event_ttl_seconds)

    async def ended(self, job: Job) -> None:
        """The job ended: tell the readers, then record its follow-up turn."""
        record = job_record("job.ended", job)
        await publish_quietly(self.thread_bus, job.key, record, self.event_ttl_seconds)
        if self.follow_ups is not None:
            await self.follow_ups.job_ended(job)
