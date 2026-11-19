"""A background job, run in-process: claim, keys, result, stops, failure reasons, the seam."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.jobs.failures import JobFailure
from app.jobs.runner import run_background_job
from app.jobs.services import JobServices, JobSettings
from app.operator_keys import OperatorKeys
from app.task_queue import InProcessEnqueuer, ToolJob
from commons.stop import StopCheck, StoppedError
from storage.job_model import Job, JobStatus
from storage.keys import ThreadKey
from tests.fakes_jobs import InMemoryJobStore
from tools.credentials import CENSUS_KEY, COMPTOX_KEY, PROVIDER_KEY
from tools.schemas import InvalidJobInputError, JobResult, JobRunner

pytestmark = pytest.mark.anyio
OWNER, OTHER = UUID(int=1), UUID(int=2)
THREAD = ThreadKey(OWNER, "t")
CENSUS = "census-" + "c0d1e2f3a4" * 3  # pragma: allowlist secret
COMPTOX = "comptox-" + "b9c8d7e6f5" * 3  # pragma: allowlist secret
USER_KEY = "sk-proj-" + "u1s2e3r4k5" * 3  # pragma: allowlist secret
FAST = JobSettings(heartbeat_seconds=0.01, soft_limit_seconds=30.0, hard_limit_seconds=60.0)
RESULT: JobResult = ({"assessed": 2}, {"facilities": [{"id": "A"}]})


class Bench:
    """A store and the services of one in-process tools worker."""

    def __init__(self, runner: JobRunner, timing: JobSettings = FAST, tool: str = "heavy") -> None:
        self.store = InMemoryJobStore()
        self.ended: list[Job] = []
        self.tool = tool
        self.services = JobServices(
            store=self.store,
            runners={"heavy": runner},
            operator=OperatorKeys(SecretStr(CENSUS), SecretStr(COMPTOX)),
            settings=timing,
            on_job_ended=self._ended,
        )

    async def _ended(self, job: Job) -> None:
        self.ended.append(job)

    async def queue(self, job_input: Mapping[str, object] | None = None, tool: str = "") -> Job:
        job = await self.store.create(THREAD, tool or self.tool, job_input or {"n": 1}, 5)
        assert job is not None
        return job

    async def run(self, job: Job, owner: UUID = OWNER) -> Job:
        await run_background_job(ToolJob(job.id, owner), self.services)
        stored = await self.store.get(OWNER, job.id)
        assert stored is not None
        return stored


def _ok(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
    return RESULT


async def test_a_job_runs_and_stores_its_result_then_calls_the_seam() -> None:
    bench = Bench(_ok)
    job = await bench.run(await bench.queue())
    assert job.status is JobStatus.SUCCEEDED and job.failure_reason is None
    assert job.result_content == {"assessed": 2} and job.result_artifact == RESULT[1]
    assert job.started_at is not None and job.ended_at is not None
    assert bench.ended == [job]


async def test_the_tool_gets_the_stored_input() -> None:
    seen: list[Mapping[str, object]] = []

    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        seen.append(arguments)
        return RESULT

    bench = Bench(runner)
    await bench.run(await bench.queue({"arguments": {"cas_number": "1-1-1"}}))
    assert seen == [{"arguments": {"cas_number": "1-1-1"}}]


async def test_a_second_delivery_runs_nothing() -> None:
    calls: list[int] = []

    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        calls.append(1)
        return RESULT

    bench = Bench(runner)
    queued = await bench.queue()
    await bench.run(queued)
    await bench.run(queued)
    assert calls == [1] and len(bench.ended) == 1


async def test_a_job_of_another_owner_is_not_run() -> None:
    calls: list[int] = []
    bench = Bench(lambda a, s: calls.append(1) or RESULT)
    queued = await bench.queue()
    await run_background_job(ToolJob(queued.id, OTHER), bench.services)
    stored = await bench.store.get(OWNER, queued.id)
    assert calls == [] and stored is not None and stored.status is JobStatus.QUEUED
    assert bench.ended == []


async def test_the_job_gets_the_operator_keys_and_never_the_users_and_releases_them() -> None:
    seen: dict[str, str | None] = {}

    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        seen["census"] = _value(CENSUS_KEY.get())
        seen["comptox"] = _value(COMPTOX_KEY.get())
        seen["provider"] = _value(PROVIDER_KEY.get())
        return RESULT

    with PROVIDER_KEY.provide(SecretStr(USER_KEY)):
        pass  # a user key set elsewhere leaves nothing behind
    bench = Bench(runner)
    await bench.run(await bench.queue())
    assert seen == {"census": CENSUS, "comptox": COMPTOX, "provider": None}
    assert CENSUS_KEY.get() is None and COMPTOX_KEY.get() is None


async def test_the_keys_are_released_when_the_job_fails() -> None:
    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        raise RuntimeError("boom")

    bench = Bench(runner)
    job = await bench.run(await bench.queue())
    assert job.status is JobStatus.FAILED
    assert CENSUS_KEY.get() is None and COMPTOX_KEY.get() is None


def _value(secret: SecretStr | None) -> str | None:
    return None if secret is None else secret.get_secret_value()


async def test_a_failure_stores_a_fixed_reason_and_never_the_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        raise RuntimeError(f"upstream said {USER_KEY} and {CENSUS}")

    bench = Bench(runner)
    with caplog.at_level(logging.WARNING, logger="app.jobs"):
        job = await bench.run(await bench.queue())
    assert job.status is JobStatus.FAILED and job.failure_reason == JobFailure.UNEXPECTED
    assert job.result_content is None and job.result_artifact is None
    assert USER_KEY not in repr(job) and CENSUS not in repr(job)
    assert bench.ended == [job]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (InvalidJobInputError("secret input"), JobFailure.BAD_INPUT),
        (KeyError("x"), JobFailure.UNEXPECTED),
        (StoppedError(), JobFailure.UNEXPECTED),  # stopped though nobody asked
    ],
)
async def test_each_failure_has_its_own_fixed_reason(error: Exception, reason: JobFailure) -> None:
    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        raise error

    bench = Bench(runner)
    job = await bench.run(await bench.queue())
    assert job.status is JobStatus.FAILED and job.failure_reason == reason


async def test_a_job_naming_an_unknown_tool_fails_without_running_anything() -> None:
    bench = Bench(_ok)
    job = await bench.run(await bench.queue(tool="other"))
    assert job.status is JobStatus.FAILED and job.failure_reason == JobFailure.UNKNOWN_TOOL


async def test_a_result_that_is_not_data_fails_as_invalid() -> None:
    bench = Bench(lambda a, s: ({"x": object()}, {}))
    job = await bench.run(await bench.queue())
    assert job.status is JobStatus.FAILED and job.failure_reason == JobFailure.INVALID_RESULT


async def test_the_result_is_redacted_and_non_finite_numbers_are_absent() -> None:
    leaky = {"note": f"key {USER_KEY}", "x": float("nan"), "ok": [1.5]}
    bench = Bench(lambda a, s: (leaky, {"c": CENSUS}))
    job = await bench.run(await bench.queue())
    assert job.status is JobStatus.SUCCEEDED
    assert USER_KEY not in repr(job.result_content) and CENSUS not in repr(job.result_artifact)
    assert job.result_content is not None and job.result_content["x"] is None
    assert job.result_content["ok"] == [1.5]


async def test_a_cancel_requested_while_it_waited_means_it_never_starts() -> None:
    calls: list[int] = []
    bench = Bench(lambda a, s: calls.append(1) or RESULT)
    queued = await bench.queue()
    await bench.store.request_cancel(OWNER, queued.id)
    job = await bench.run(queued)
    assert calls == [] and job.status is JobStatus.CANCELLED
    assert job.failure_reason == JobFailure.CANCELLED and bench.ended == [job]


def _until_stopped(started: threading.Event | None = None) -> JobRunner:
    """A tool that works in tiers until it is told to stop (as the assessment does)."""

    def runner(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        if started is not None:
            started.set()
        for _ in range(500):
            if should_stop():
                raise StoppedError
            time.sleep(0.01)
        return RESULT

    return runner


async def test_a_cancel_request_stops_a_running_job_between_its_tiers() -> None:
    started = threading.Event()
    bench = Bench(_until_stopped(started))
    queued = await bench.queue()
    running = asyncio.create_task(bench.run(queued))
    while not started.is_set():
        await asyncio.sleep(0.005)
    assert await bench.store.request_cancel(OWNER, queued.id)
    job = await asyncio.wait_for(running, 5)
    assert job.status is JobStatus.CANCELLED and job.failure_reason == JobFailure.CANCELLED
    assert job.result_content is None and bench.ended == [job]


async def test_the_soft_limit_stops_the_job_at_its_next_check() -> None:
    timing = JobSettings(heartbeat_seconds=0.01, soft_limit_seconds=0.1, hard_limit_seconds=60.0)
    bench = Bench(_until_stopped(), timing)
    job = await asyncio.wait_for(bench.run(await bench.queue()), 5)
    assert job.status is JobStatus.FAILED and job.failure_reason == JobFailure.TIME_LIMIT


async def test_a_tool_that_ignores_the_stop_is_abandoned_halfway_to_the_hard_limit() -> None:
    release = threading.Event()

    def stubborn(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
        release.wait(5)
        return RESULT

    timing = JobSettings(heartbeat_seconds=0.01, soft_limit_seconds=0.05, hard_limit_seconds=0.15)
    bench = Bench(stubborn, timing)
    try:
        job = await asyncio.wait_for(bench.run(await bench.queue()), 5)
    finally:
        release.set()
    assert job.status is JobStatus.FAILED and job.failure_reason == JobFailure.TIME_LIMIT
    assert job.result_content is None


async def test_the_heartbeat_is_renewed_while_the_job_runs() -> None:
    started = threading.Event()
    bench = Bench(_until_stopped(started))
    queued = await bench.queue()
    running = asyncio.create_task(bench.run(queued))
    while not started.is_set():
        await asyncio.sleep(0.005)
    first = await bench.store.get(OWNER, queued.id)
    await asyncio.sleep(0.1)
    later = await bench.store.get(OWNER, queued.id)
    await bench.store.request_cancel(OWNER, queued.id)
    await asyncio.wait_for(running, 5)
    assert first is not None and later is not None
    assert first.heartbeat_at is not None and later.heartbeat_at is not None
    assert later.heartbeat_at > first.heartbeat_at


async def test_a_job_interrupted_meanwhile_is_not_overwritten_and_does_not_follow_up() -> None:
    started = threading.Event()
    bench = Bench(_until_stopped(started))
    queued = await bench.queue()
    running = asyncio.create_task(bench.run(queued))
    while not started.is_set():
        await asyncio.sleep(0.005)
    await bench.store.interrupt(OWNER, queued.id, "worker_lost")
    job = await asyncio.wait_for(running, 5)
    assert job.status is JobStatus.INTERRUPTED and bench.ended == []


async def test_a_failing_follow_up_does_not_change_the_job() -> None:
    bench = Bench(_ok)

    async def broken(job: Job) -> None:
        raise RuntimeError("follow-up down")

    services = JobServices(
        bench.store,
        bench.services.runners,
        bench.services.operator,
        FAST,
        broken,
    )
    queued = await bench.queue()
    await run_background_job(ToolJob(queued.id, OWNER), services)
    stored = await bench.store.get(OWNER, queued.id)
    assert stored is not None and stored.status is JobStatus.SUCCEEDED


async def test_the_in_process_enqueuer_runs_the_job_through_the_same_runner() -> None:
    bench = Bench(_ok)
    queued = await bench.queue()

    async def run(task: ToolJob) -> None:
        await run_background_job(task, bench.services)

    enqueuer: Any = InProcessEnqueuer(run)
    await enqueuer.enqueue(ToolJob(queued.id, OWNER))
    await enqueuer.drain()
    stored = await bench.store.get(OWNER, queued.id)
    assert stored is not None and stored.status is JobStatus.SUCCEEDED
