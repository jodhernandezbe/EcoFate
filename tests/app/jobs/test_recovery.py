"""Stale and lost jobs become interrupted; nothing is re-run; the seam hears of each."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.jobs.failures import JobFailure
from app.jobs.recovery import interrupt_lost_job, sweep_stale_jobs
from app.task_queue import ToolJob
from storage.job_model import Job, JobStatus
from storage.keys import ThreadKey
from tests.fakes_jobs import InMemoryJobStore

pytestmark = pytest.mark.anyio
OWNER = UUID(int=1)
KEY = ThreadKey(OWNER, "t")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _running(store: InMemoryJobStore) -> Job:
    job = await store.create(KEY, "heavy", {}, 9)
    assert job is not None
    claimed = await store.claim(OWNER, job.id)
    assert claimed is not None
    return claimed


async def test_the_sweep_interrupts_stale_running_jobs_and_tells_the_seam() -> None:
    clock = Clock()
    store, heard = InMemoryJobStore(clock), []
    job = await _running(store)
    clock.now += timedelta(minutes=10)

    async def hear(ended: Job) -> None:
        heard.append(ended)

    assert await sweep_stale_jobs(store, timedelta(minutes=5), hear) == 1
    stored = await store.get(OWNER, job.id)
    assert stored is not None and stored.status is JobStatus.INTERRUPTED
    assert stored.failure_reason == JobFailure.WORKER_LOST and heard == [stored]
    assert await sweep_stale_jobs(store, timedelta(minutes=5), hear) == 0


async def test_a_fresh_job_and_a_queued_one_are_left_alone() -> None:
    clock = Clock()
    store = InMemoryJobStore(clock)
    fresh = await _running(store)
    queued = await store.create(KEY, "heavy", {}, 9)
    clock.now += timedelta(minutes=1)
    assert await sweep_stale_jobs(store, timedelta(minutes=5)) == 0
    assert (await store.get(OWNER, fresh.id)) == fresh
    assert queued is not None and (await store.get(OWNER, queued.id)) == queued


async def test_a_lost_task_interrupts_its_open_job_once() -> None:
    store = InMemoryJobStore()
    job = await _running(store)
    task = ToolJob(job.id, OWNER)
    assert await interrupt_lost_job(store, task, JobFailure.TIME_LIMIT) is True
    stored = await store.get(OWNER, job.id)
    assert stored is not None and stored.failure_reason == JobFailure.TIME_LIMIT
    assert await interrupt_lost_job(store, task, JobFailure.WORKER_LOST) is False


async def test_a_lost_task_cannot_interrupt_another_users_job() -> None:
    store = InMemoryJobStore()
    job = await _running(store)
    assert (
        await interrupt_lost_job(store, ToolJob(job.id, UUID(int=2)), JobFailure.WORKER_LOST)
        is False
    )
    stored = await store.get(OWNER, job.id)
    assert stored is not None and stored.status is JobStatus.RUNNING
