"""An in-memory job store with the contract of ``storage.jobs.PostgresJobStore``."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from storage.job_model import OPEN_STATUSES, Job, JobOutcome, JobStatus, JsonObject
from storage.keys import ThreadKey


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryJobStore:
    """The ``JobStore`` contract in process memory: owner-scoped reads, the per-owner cap, the
    same moves and refusals as PostgreSQL.

    Args:
        clock: The time source (a test fixes it to age a heartbeat).
    """

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._jobs: dict[str, Job] = {}  # in creation order
        self._count = 0

    def _mine(self, owner_id: UUID, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        return copy.deepcopy(job) if job is not None and job.owner_id == owner_id else None

    def _set(self, job: Job, **changes: object) -> Job:
        self._jobs[job.id] = replace(job, **changes)  # pyright: ignore[reportArgumentType]
        return copy.deepcopy(self._jobs[job.id])

    async def create(
        self,
        key: ThreadKey,
        tool: str,
        job_input: JsonObject,
        max_open: int,
    ) -> Job | None:
        open_jobs = [j for j in self._jobs.values() if j.owner_id == key.owner_id]
        if sum(1 for j in open_jobs if j.status in OPEN_STATUSES) >= max_open:
            return None
        self._count += 1
        job = Job(
            f"{self._count:032x}",
            key.owner_id,
            key.thread_id,
            tool,
            copy.deepcopy(dict(job_input)),
            JobStatus.QUEUED,
            self._clock(),
        )
        self._jobs[job.id] = job
        return copy.deepcopy(job)

    async def get(self, owner_id: UUID, job_id: str) -> Job | None:
        return self._mine(owner_id, job_id)

    async def claim(self, owner_id: UUID, job_id: str) -> Job | None:
        job = self._mine(owner_id, job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            return None
        now = self._clock()
        return self._set(job, status=JobStatus.RUNNING, started_at=now, heartbeat_at=now)

    async def heartbeat(self, owner_id: UUID, job_id: str) -> bool:
        job = self._mine(owner_id, job_id)
        if job is None or job.status is not JobStatus.RUNNING:
            return False
        self._set(job, heartbeat_at=self._clock())
        return True

    async def request_cancel(self, owner_id: UUID, job_id: str) -> bool:
        job = self._mine(owner_id, job_id)
        if job is None or job.status not in OPEN_STATUSES:
            return False
        self._set(job, cancel_requested=True)
        return True

    async def cancel_requested(self, owner_id: UUID, job_id: str) -> bool:
        job = self._mine(owner_id, job_id)
        return job is not None and job.cancel_requested

    async def finish(self, owner_id: UUID, job_id: str, outcome: JobOutcome) -> Job | None:
        job = self._mine(owner_id, job_id)
        if job is None or job.status is not JobStatus.RUNNING:
            return None
        return self._set(
            job,
            status=outcome.status,
            ended_at=self._clock(),
            result_content=copy.deepcopy(outcome.content),
            result_artifact=copy.deepcopy(outcome.artifact),
            failure_reason=outcome.reason,
        )

    async def interrupt(self, owner_id: UUID, job_id: str, reason: str) -> Job | None:
        job = self._mine(owner_id, job_id)
        if job is None or job.status not in OPEN_STATUSES:
            return None
        return self._set(
            job,
            status=JobStatus.INTERRUPTED,
            ended_at=self._clock(),
            failure_reason=reason,
        )

    async def interrupt_stale(self, older_than: timedelta, reason: str) -> list[Job]:
        limit = self._clock() - older_than
        stale = [j for j in self._jobs.values() if j.status is JobStatus.RUNNING]
        stale = [j for j in stale if (j.heartbeat_at or j.started_at or j.queued_at) < limit]
        return [await self.interrupt(j.owner_id, j.id, reason) for j in stale]  # type: ignore[misc]

    async def for_thread(self, key: ThreadKey) -> list[Job]:
        found = [j for j in self._jobs.values() if j.key == key]
        return [copy.deepcopy(j) for j in found]
