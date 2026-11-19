"""PostgreSQL behaviour of the job store and the 0007 migration (``postgres`` marker): the
atomic per-owner cap under concurrency, owner scoping, guarded moves, the stale sweep, the
cascade with the thread and the stored-row checks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from storage.job_model import JobOutcome, JobStatus
from storage.jobs import PostgresJobStore
from storage.keys import ThreadKey
from tests.postgres import Database, add_user, database

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
CAP = 2
SUCCESS = JobOutcome(JobStatus.SUCCEEDED, {"facilities": []}, {"assessed": []})


@dataclass
class Bench:
    db: Database
    store: PostgresJobStore
    alice: UUID
    bob: UUID

    def key(self, owner: UUID | None = None, thread: str = "t1") -> ThreadKey:
        return ThreadKey(owner or self.alice, thread)


async def _thread(engine: AsyncEngine, key: ThreadKey) -> None:
    statement = text(
        "INSERT INTO threads (owner_id, id) VALUES (:owner, :id) ON CONFLICT DO NOTHING",
    )
    async with engine.begin() as connection:
        await connection.execute(statement, {"owner": key.owner_id, "id": key.thread_id})


@pytest.fixture
async def bench() -> AsyncGenerator[Bench]:
    async with database() as db:
        alice, bob = await add_user(db.engine, uuid4()), await add_user(db.engine, uuid4())
        made = Bench(db, PostgresJobStore(async_sessionmaker(db.engine)), alice, bob)
        for key in (made.key(), made.key(bob)):
            await _thread(db.engine, key)
        yield made


async def _running(bench: Bench) -> str:
    job = await bench.store.create(bench.key(), "assess_facilities", {"cas": "1"}, CAP)
    assert job is not None
    assert await bench.store.claim(bench.alice, job.id) is not None
    return job.id


async def test_a_job_is_recorded_queued_and_read_back_by_its_owner_only(bench: Bench) -> None:
    job = await bench.store.create(bench.key(), "assess_facilities", {"cas_number": "1"}, CAP)
    assert job is not None and job.status is JobStatus.QUEUED
    assert job.input == {"cas_number": "1"}
    assert await bench.store.get(bench.alice, job.id) == job
    assert await bench.store.get(bench.bob, job.id) is None
    assert await bench.store.claim(bench.bob, job.id) is None
    assert await bench.store.request_cancel(bench.bob, job.id) is False


async def test_concurrent_creates_never_exceed_the_cap(bench: Bench) -> None:
    results = await asyncio.gather(
        *(bench.store.create(bench.key(), "assess_facilities", {}, CAP) for _ in range(8)),
    )
    assert sum(job is not None for job in results) == CAP
    assert len(await bench.store.for_thread(bench.key())) == CAP
    other = await bench.store.create(bench.key(bench.bob), "assess_facilities", {}, CAP)
    assert other is not None  # the cap is per owner


async def test_an_ended_job_frees_a_place(bench: Bench) -> None:
    first = await _running(bench)
    await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    assert await bench.store.create(bench.key(), "assess_facilities", {}, CAP) is None
    assert await bench.store.finish(bench.alice, first, SUCCESS) is not None
    assert await bench.store.create(bench.key(), "assess_facilities", {}, CAP) is not None


async def test_only_one_of_two_claims_wins(bench: Bench) -> None:
    job = await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    assert job is not None
    claims = await asyncio.gather(*(bench.store.claim(bench.alice, job.id) for _ in range(4)))
    assert sum(claim is not None for claim in claims) == 1


async def test_finish_stores_the_result_once_and_failure_needs_its_reason(bench: Bench) -> None:
    job_id = await _running(bench)
    ended = await bench.store.finish(bench.alice, job_id, SUCCESS)
    assert ended is not None and ended.result_artifact == {"assessed": []} and ended.ended_at
    assert await bench.store.finish(bench.alice, job_id, SUCCESS) is None
    failed_id = await _running(bench)
    failed = await bench.store.finish(
        bench.alice,
        failed_id,
        JobOutcome(JobStatus.FAILED, reason="unexpected"),
    )
    assert failed is not None and failed.failure_reason == "unexpected"


async def test_cancel_and_heartbeat(bench: Bench) -> None:
    job_id = await _running(bench)
    assert await bench.store.heartbeat(bench.alice, job_id) is True
    assert await bench.store.cancel_requested(bench.alice, job_id) is False
    assert await bench.store.request_cancel(bench.alice, job_id) is True
    assert await bench.store.cancel_requested(bench.alice, job_id) is True
    await bench.store.finish(
        bench.alice,
        job_id,
        JobOutcome(JobStatus.CANCELLED, reason="cancelled"),
    )
    assert await bench.store.heartbeat(bench.alice, job_id) is False
    assert await bench.store.request_cancel(bench.alice, job_id) is False


async def test_the_stale_sweep_interrupts_only_old_running_jobs(bench: Bench) -> None:
    stale, fresh = await _running(bench), await _running(bench)
    async with bench.db.engine.begin() as connection:
        await connection.execute(
            text("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": stale},
        )
    swept = await bench.store.interrupt_stale(timedelta(minutes=5), "worker_lost")
    assert [job.id for job in swept] == [stale]
    assert swept[0].status is JobStatus.INTERRUPTED and swept[0].failure_reason == "worker_lost"
    assert await bench.store.finish(bench.alice, stale, SUCCESS) is None
    again = await bench.store.get(bench.alice, fresh)
    assert again is not None and again.status is JobStatus.RUNNING


async def test_a_job_row_with_a_reason_that_does_not_fit_its_status_is_refused(
    bench: Bench,
) -> None:
    job = await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    assert job is not None
    async with bench.db.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(
                text("UPDATE jobs SET status = 'failed' WHERE id = :id"),
                {"id": job.id},
            )


async def test_deleting_the_thread_deletes_its_jobs(bench: Bench) -> None:
    job = await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    assert job is not None
    async with bench.db.engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM threads WHERE owner_id = :o"),
            {"o": bench.alice},
        )
    assert await bench.store.get(bench.alice, job.id) is None


async def test_an_undecodable_row_is_absent(bench: Bench) -> None:
    job = await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    assert job is not None
    async with bench.db.engine.begin() as connection:
        await connection.execute(
            text("UPDATE jobs SET input = '[1]'::jsonb WHERE id = :id"),
            {"id": job.id},
        )
    assert await bench.store.get(bench.alice, job.id) is None


async def test_a_queued_job_is_cancelled_at_once_and_only_by_its_owner(bench: Bench) -> None:
    job = await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    assert job is not None
    assert await bench.store.cancel_queued(bench.bob, job.id, "cancelled") is None
    ended = await bench.store.cancel_queued(bench.alice, job.id, "cancelled")
    assert ended is not None and ended.status is JobStatus.CANCELLED
    assert await bench.store.claim(bench.alice, job.id) is None
    running = await _running(bench)
    assert await bench.store.cancel_queued(bench.alice, running, "cancelled") is None


async def test_the_unclaimed_sweep_and_the_queue_position(bench: Bench) -> None:
    first = await bench.store.create(bench.key(), "assess_facilities", {}, CAP)
    other = await bench.store.create(bench.key(bench.bob), "assess_facilities", {}, CAP)
    assert first is not None and other is not None
    assert await bench.store.queue_position(bench.alice, first.id) == 0
    assert await bench.store.queue_position(bench.bob, other.id) == 1
    assert await bench.store.queue_position(bench.alice, other.id) == 0  # not found
    assert await bench.store.interrupt_unclaimed(timedelta(hours=1), "not_started") == []
    async with bench.db.engine.begin() as connection:
        await connection.execute(text("UPDATE jobs SET queued_at = now() - interval '2 hours'"))
    swept = await bench.store.interrupt_unclaimed(timedelta(hours=1), "not_started")
    assert {j.id for j in swept} == {first.id, other.id}
    assert all(j.status is JobStatus.INTERRUPTED for j in swept)
