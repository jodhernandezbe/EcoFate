"""The job store contract, run against the in-memory store (the PostgreSQL store runs the same
cases in ``test_postgres_jobs.py``): the per-owner cap, owner scoping, claims, heartbeat, cancel,
finish, the stale sweep and the outcome rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from storage.job_model import Job, JobOutcome, JobStatus, JobStore
from storage.keys import ThreadKey
from tests.fakes_jobs import InMemoryJobStore

pytestmark = pytest.mark.anyio
ALICE, BOB = UUID(int=1), UUID(int=2)
THREAD = ThreadKey(ALICE, "t1")
SUCCESS = JobOutcome(JobStatus.SUCCEEDED, {"facilities": []}, {"assessed": []})
CAP = 2


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _queued(store: JobStore, key: ThreadKey = THREAD) -> Job:
    job = await store.create(key, "assess_facilities", {"cas_number": "110-54-3"}, CAP)
    assert job is not None
    return job


async def _running(store: JobStore, key: ThreadKey = THREAD) -> Job:
    queued = await _queued(store, key)
    claimed = await store.claim(queued.owner_id, queued.id)
    assert claimed is not None
    return claimed


async def test_a_new_job_is_queued_with_its_input() -> None:
    job = await _queued(InMemoryJobStore())
    assert job.status is JobStatus.QUEUED
    assert job.input == {"cas_number": "110-54-3"} and job.started_at is None


async def test_the_owner_cannot_exceed_the_cap_of_open_jobs() -> None:
    store = InMemoryJobStore()
    await _queued(store)
    await _queued(store)
    assert await store.create(THREAD, "assess_facilities", {}, CAP) is None
    assert len(await store.for_thread(THREAD)) == CAP


async def test_the_cap_counts_per_owner_and_frees_when_a_job_ends() -> None:
    store = InMemoryJobStore()
    first = await _running(store)
    await _queued(store)
    assert await _queued(store, ThreadKey(BOB, "t1"))  # another user has their own cap
    assert await store.finish(ALICE, first.id, SUCCESS) is not None
    assert await store.create(THREAD, "assess_facilities", {}, CAP) is not None


async def test_a_foreign_job_looks_like_an_unknown_one() -> None:
    store = InMemoryJobStore()
    job = await _queued(store)
    assert await store.get(BOB, job.id) is None
    assert await store.get(ALICE, "0" * 32) is None
    assert await store.claim(BOB, job.id) is None
    assert await store.request_cancel(BOB, job.id) is False
    assert await store.finish(BOB, job.id, SUCCESS) is None
    assert await store.for_thread(ThreadKey(BOB, THREAD.thread_id)) == []
    assert (await store.get(ALICE, job.id)) == job  # untouched


async def test_a_second_claim_does_nothing() -> None:
    store = InMemoryJobStore()
    queued = await _queued(store)
    first = await store.claim(ALICE, queued.id)
    assert first is not None and first.status is JobStatus.RUNNING
    assert first.started_at is not None and first.heartbeat_at is not None
    assert await store.claim(ALICE, queued.id) is None


async def test_a_heartbeat_only_renews_a_running_job() -> None:
    clock = Clock()
    store = InMemoryJobStore(clock)
    queued = await _queued(store)
    assert await store.heartbeat(ALICE, queued.id) is False
    await store.claim(ALICE, queued.id)
    clock.now += timedelta(seconds=5)
    assert await store.heartbeat(ALICE, queued.id) is True
    job = await store.get(ALICE, queued.id)
    assert job is not None and job.heartbeat_at == clock.now


async def test_a_cancel_request_is_recorded_for_an_open_job_only() -> None:
    store = InMemoryJobStore()
    job = await _running(store)
    assert await store.cancel_requested(ALICE, job.id) is False
    assert await store.request_cancel(ALICE, job.id) is True
    assert await store.cancel_requested(ALICE, job.id) is True
    await store.finish(ALICE, job.id, JobOutcome(JobStatus.CANCELLED, reason="cancelled"))
    assert await store.request_cancel(ALICE, job.id) is False


async def test_finishing_stores_the_result_and_a_second_finish_does_nothing() -> None:
    store = InMemoryJobStore()
    job = await _running(store)
    ended = await store.finish(ALICE, job.id, SUCCESS)
    assert ended is not None and ended.status is JobStatus.SUCCEEDED and ended.ended_at
    assert ended.result_content == {"facilities": []} and ended.failure_reason is None
    assert await store.finish(ALICE, job.id, SUCCESS) is None


async def test_a_job_that_is_not_running_cannot_be_finished() -> None:
    store = InMemoryJobStore()
    queued = await _queued(store)
    assert await store.finish(ALICE, queued.id, SUCCESS) is None


async def test_a_failed_job_keeps_its_fixed_reason() -> None:
    store = InMemoryJobStore()
    job = await _running(store)
    ended = await store.finish(ALICE, job.id, JobOutcome(JobStatus.FAILED, reason="time_limit"))
    assert ended is not None and ended.failure_reason == "time_limit"
    assert ended.result_content is None


async def test_the_stale_sweep_interrupts_only_running_jobs_with_an_old_heartbeat() -> None:
    clock = Clock()
    store = InMemoryJobStore(clock)
    old = await _running(store)
    clock.now += timedelta(seconds=100)
    fresh = await _running(store, ThreadKey(BOB, "t"))
    swept = await store.interrupt_stale(timedelta(seconds=50), "worker_lost")
    assert [j.id for j in swept] == [old.id]
    interrupted = await store.get(ALICE, old.id)
    assert interrupted is not None and interrupted.status is JobStatus.INTERRUPTED
    assert interrupted.failure_reason == "worker_lost"
    assert (await store.get(BOB, fresh.id)) == fresh
    assert await store.interrupt_stale(timedelta(seconds=50), "worker_lost") == []


async def test_a_job_interrupted_by_the_sweep_cannot_be_finished_by_its_late_worker() -> None:
    clock = Clock()
    store = InMemoryJobStore(clock)
    job = await _running(store)
    clock.now += timedelta(seconds=100)
    await store.interrupt_stale(timedelta(seconds=50), "worker_lost")
    assert await store.finish(ALICE, job.id, SUCCESS) is None


async def test_interrupting_names_an_open_job_of_the_owner() -> None:
    store = InMemoryJobStore()
    job = await _queued(store)
    assert await store.interrupt(BOB, job.id, "worker_lost") is None
    moved = await store.interrupt(ALICE, job.id, "worker_lost")
    assert moved is not None and moved.status is JobStatus.INTERRUPTED
    assert await store.interrupt(ALICE, job.id, "worker_lost") is None


async def test_the_jobs_of_a_thread_come_oldest_first_for_that_thread_only() -> None:
    store = InMemoryJobStore()
    a, b = await _queued(store), await _queued(store)
    await store.create(ThreadKey(ALICE, "other"), "assess_facilities", {}, 9)
    assert [j.id for j in await store.for_thread(THREAD)] == [a.id, b.id]


@pytest.mark.parametrize(
    "outcome",
    [
        lambda: JobOutcome(JobStatus.SUCCEEDED),
        lambda: JobOutcome(JobStatus.SUCCEEDED, {}, {}, "why"),
        lambda: JobOutcome(JobStatus.FAILED),
        lambda: JobOutcome(JobStatus.FAILED, {}, None, "why"),
        lambda: JobOutcome(JobStatus.CANCELLED, reason=""),
        lambda: JobOutcome(JobStatus.INTERRUPTED, reason="worker_lost"),
        lambda: JobOutcome(JobStatus.RUNNING),
    ],
)
def test_an_outcome_that_does_not_fit_its_status_is_refused(outcome: object) -> None:
    assert callable(outcome)
    with pytest.raises(ValueError, match="job|result|reason|artifact"):
        outcome()


async def test_a_queued_job_can_be_cancelled_at_once_and_frees_the_cap() -> None:
    store = InMemoryJobStore()
    job = await _queued(store)
    await _queued(store)
    ended = await store.cancel_queued(ALICE, job.id, "cancelled")
    assert ended is not None and ended.status is JobStatus.CANCELLED
    assert ended.failure_reason == "cancelled" and ended.ended_at is not None
    assert await store.claim(ALICE, job.id) is None  # a late delivery runs nothing
    assert await store.create(THREAD, "assess_facilities", {}, CAP) is not None


async def test_only_a_queued_job_of_the_owner_is_cancelled_at_once() -> None:
    store = InMemoryJobStore()
    queued, running = await _queued(store), await _running(store)
    assert await store.cancel_queued(BOB, queued.id, "cancelled") is None
    assert await store.cancel_queued(ALICE, running.id, "cancelled") is None
    assert (await store.get(ALICE, running.id)) == running
    assert (await store.get(ALICE, queued.id)) == queued


async def test_the_unclaimed_sweep_interrupts_only_old_queued_jobs() -> None:
    clock = Clock()
    store = InMemoryJobStore(clock)
    old, running = await _queued(store), await _running(store, ThreadKey(BOB, "b"))
    clock.now += timedelta(hours=2)
    fresh = await _queued(store, ThreadKey(BOB, "b2"))
    swept = await store.interrupt_unclaimed(timedelta(hours=1), "not_started")
    assert [j.id for j in swept] == [old.id] and swept[0].status is JobStatus.INTERRUPTED
    assert (await store.get(BOB, running.id)) == running
    assert (await store.get(BOB, fresh.id)) == fresh


async def test_the_queue_position_counts_the_queued_jobs_before_it_of_any_user() -> None:
    store = InMemoryJobStore()
    first = await _queued(store)
    other = await _queued(store, ThreadKey(BOB, "b"))
    second = await _queued(store)
    await store.claim(ALICE, first.id)
    assert await store.queue_position(BOB, other.id) == 0
    assert await store.queue_position(ALICE, second.id) == 1
    assert await store.queue_position(ALICE, first.id) == 0  # running: not queued
    assert await store.queue_position(BOB, second.id) == 0  # another user's job: not found
