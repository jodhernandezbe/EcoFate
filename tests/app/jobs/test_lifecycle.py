"""What a job's start and end tell the thread's readers and the follow-up, through the runner."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.jobs.lifecycle import JobLifecycle
from app.jobs.runner import run_background_job
from app.jobs.services import JobServices, JobSettings
from app.operator_keys import OperatorKeys
from app.task_queue import ToolJob, TurnJob
from app.turns.bus import MemoryBus
from app.turns.follow_up import FollowUps
from app.turns.thread_bus import MemoryThreadBus, thread_stream
from commons.stop import StopCheck
from storage.job_model import JobStatus
from storage.keys import ThreadKey
from tests.fakes import InMemoryThreadStore
from tools.schemas import JobResult

pytestmark = pytest.mark.anyio
OWNER = UUID(int=1)
THREAD = ThreadKey(OWNER, "t")
FAST = JobSettings(heartbeat_seconds=0.01, soft_limit_seconds=30.0, hard_limit_seconds=60.0)


class Turns:
    def __init__(self) -> None:
        self.sent: list[TurnJob] = []

    async def enqueue(self, job: TurnJob) -> None:
        self.sent.append(job)


def _services(store: InMemoryThreadStore, turns: Turns, bus: MemoryThreadBus) -> JobServices:
    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        return {"assessed": 1}, {"assessed": [], "screened_out": [], "not_assessed": []}

    follow_ups = FollowUps(store, MemoryBus(), turns, 60)
    lifecycle = JobLifecycle(bus, 60, follow_ups)
    return JobServices(
        store=store.jobs,
        runners={"heavy": runner},
        operator=OperatorKeys(SecretStr("c"), SecretStr("d")),
        settings=FAST,
        on_job_ended=lifecycle.ended,
        on_job_started=lifecycle.started,
    )


async def test_a_job_publishes_running_and_ended_then_starts_one_follow_up() -> None:
    store, turns, bus = InMemoryThreadStore(), Turns(), MemoryThreadBus()
    job = await store.jobs.create(THREAD, "heavy", {"arguments": {}}, 3)
    assert job is not None
    services = _services(store, turns, bus)
    await run_background_job(ToolJob(job.id, OWNER), services)
    await run_background_job(ToolJob(job.id, OWNER), services)  # a second delivery
    kinds = [e["kind"] for _, e in await bus.read(thread_stream(THREAD), None, 0.01)]
    assert kinds == ["job.running", "job.ended"]
    ended = [e for _, e in await bus.read(thread_stream(THREAD), None, 0.01)][-1]
    assert ended == {"kind": "job.ended", "job_id": job.id, "tool": "heavy", "status": "succeeded"}
    assert len(turns.sent) == 1  # one follow-up for the job
    stored = await store.jobs.get(OWNER, job.id)
    assert stored is not None and stored.status is JobStatus.SUCCEEDED


async def test_a_failing_follow_up_never_changes_the_job() -> None:
    store, bus = InMemoryThreadStore(), MemoryThreadBus()

    class Down:
        async def enqueue(self, job: TurnJob) -> None:
            raise RuntimeError("boom")

    services = _services(store, Turns(), bus)
    lifecycle = JobLifecycle(bus, 60, FollowUps(store, MemoryBus(), Down(), 60))  # type: ignore[arg-type]
    services = JobServices(
        store=services.store,
        runners=services.runners,
        operator=services.operator,
        settings=FAST,
        on_job_ended=lifecycle.ended,
    )
    job = await store.jobs.create(THREAD, "heavy", {"arguments": {}}, 3)
    assert job is not None
    await run_background_job(ToolJob(job.id, OWNER), services)
    stored = await store.jobs.get(OWNER, job.id)
    assert stored is not None and stored.status is JobStatus.SUCCEEDED
