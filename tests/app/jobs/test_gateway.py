"""The job gateway the heavy tools use: the cap, the owner, the queue and what status reveals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.jobs.failures import JobFailure
from app.jobs.gateway import JobGateway
from app.task_queue import EnqueueError, ToolJob
from app.turns.thread_bus import MemoryThreadBus, thread_stream
from storage.job_model import JobOutcome, JobStatus
from storage.keys import ThreadKey
from tests.fakes_jobs import InMemoryJobStore
from tools.jobs.port import JobUnavailableError

pytestmark = pytest.mark.anyio
ME, OTHER = UUID(int=1), UUID(int=2)
INPUT = {"arguments": {"cas_number": "110-54-3"}}


class Enqueuer:
    def __init__(self, *, down: bool = False) -> None:
        self.sent: list[ToolJob] = []
        self.down = down

    async def enqueue(self, job: ToolJob) -> None:
        if self.down:
            raise EnqueueError("ConnectionError")
        self.sent.append(job)


def _gateway(
    store: InMemoryJobStore,
    enqueuer: Enqueuer,
    bus: MemoryThreadBus | None = None,
    *,
    max_open: int = 2,
    now: datetime | None = None,
) -> JobGateway:
    clock = (lambda: now) if now is not None else (lambda: datetime.now(UTC))
    return JobGateway(store, enqueuer, max_open, bus, 60, clock)


async def test_a_job_is_recorded_queued_announced_and_sent_by_ids_only() -> None:
    store, enqueuer, bus = InMemoryJobStore(), Enqueuer(), MemoryThreadBus()
    answer = await _gateway(store, enqueuer, bus).submit(ME, "t1", "assess_facilities", INPUT)
    assert answer is not None and answer["status"] == "queued" and answer["position"] == 0
    (sent,) = enqueuer.sent
    assert sent.payload() == [answer["job_id"], str(ME)]
    (job,) = await store.for_thread(ThreadKey(ME, "t1"))
    assert job.status is JobStatus.QUEUED and job.input == INPUT
    ((_, event),) = await bus.read(thread_stream(ThreadKey(ME, "t1")), None, 0.01)
    assert event == {
        "kind": "job.queued",
        "job_id": job.id,
        "tool": "assess_facilities",
        "status": "queued",
    }


async def test_over_the_cap_nothing_is_recorded_or_sent() -> None:
    store, enqueuer = InMemoryJobStore(), Enqueuer()
    gateway = _gateway(store, enqueuer, max_open=1)
    assert await gateway.submit(ME, "t1", "assess_facilities", INPUT) is not None
    assert await gateway.submit(ME, "t2", "assess_facilities", INPUT) is None
    assert len(enqueuer.sent) == 1 and len(await store.for_thread(ThreadKey(ME, "t2"))) == 0
    assert await gateway.submit(OTHER, "t1", "assess_facilities", INPUT) is not None  # per owner


async def test_a_queue_that_cannot_be_reached_leaves_no_queued_job() -> None:
    store, bus = InMemoryJobStore(), MemoryThreadBus()
    with pytest.raises(JobUnavailableError):
        await _gateway(store, Enqueuer(down=True), bus).submit(ME, "t1", "x", INPUT)
    (job,) = await store.for_thread(ThreadKey(ME, "t1"))
    assert job.status is JobStatus.INTERRUPTED and job.failure_reason == JobFailure.NOT_STARTED
    # it does not hold the owner's cap
    assert await _gateway(store, Enqueuer(), max_open=1).submit(ME, "t1", "x", INPUT) is not None
    kinds = [e["kind"] for _, e in await bus.read(thread_stream(job.key), None, 0.01)]
    assert kinds == ["job.queued", "job.ended"]


async def test_status_lists_only_the_owners_jobs_of_the_thread() -> None:
    store, enqueuer = InMemoryJobStore(), Enqueuer()
    gateway = _gateway(store, enqueuer)
    mine = await gateway.submit(ME, "t1", "assess_facilities", INPUT)
    theirs = await gateway.submit(OTHER, "t1", "assess_facilities", INPUT)
    await gateway.submit(ME, "t2", "assess_facilities", INPUT)
    assert mine is not None and theirs is not None
    found = await gateway.status(ME, "t1", None)
    assert [e["job_id"] for e in found] == [mine["job_id"]]
    assert await gateway.status(ME, "t1", theirs["job_id"]) == []  # a foreign id looks unknown
    assert await gateway.status(OTHER, "t2", None) == []


async def test_status_reports_position_elapsed_time_and_a_short_outcome_never_a_result() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    store, enqueuer = InMemoryJobStore(lambda: start), Enqueuer()
    gateway = _gateway(store, enqueuer, now=start + timedelta(seconds=75))
    first = await gateway.submit(ME, "t1", "assess_facilities", INPUT)
    second = await gateway.submit(OTHER, "t9", "assess_facilities", INPUT)
    assert first is not None and second is not None
    (queued,) = await gateway.status(OTHER, "t9", None)
    assert queued.get("position") == 1 and queued["elapsed_seconds"] == 75.0
    await store.claim(ME, first["job_id"])
    done = JobOutcome(JobStatus.SUCCEEDED, {"secret_figure": 42}, {"facilities": []})
    await store.finish(ME, first["job_id"], done)
    (ended,) = await gateway.status(ME, "t1", None)
    assert ended["status"] == "succeeded" and "position" not in ended
    assert "follow-up" in ended.get("outcome", "") and "42" not in str(ended)
