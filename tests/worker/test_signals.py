"""The worker's signals: a lost job task interrupts its job, a lost turn task its turn."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from celery.exceptions import TimeLimitExceeded, WorkerLostError

from app.task_queue import JOB_TASK_NAME, TASK_NAME, ToolJob, TurnJob
from app.turns.failures import FailureReason
from worker import celery_app

OWNER = UUID(int=3)
IDS = ["d" * 32, str(OWNER)]


class _Task:
    def __init__(self, name: str) -> None:
        self.name = name


class Calls:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.jobs: list[tuple[ToolJob, FailureReason]] = []
        self.turns: list[tuple[TurnJob, FailureReason]] = []
        monkeypatch.setattr(celery_app.recovery, "interrupt_lost_job_env", self._job)
        monkeypatch.setattr(celery_app.recovery, "interrupt_lost_env", self._turn)

    async def _job(self, job: ToolJob, reason: FailureReason, environ: Any) -> bool:
        self.jobs.append((job, reason))
        return True

    async def _turn(self, job: TurnJob, reason: FailureReason, environ: Any) -> bool:
        self.turns.append((job, reason))
        return True


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    return Calls(monkeypatch)


def test_a_lost_job_task_interrupts_its_job_not_a_turn(calls: Calls) -> None:
    celery_app._task_failed(_Task(JOB_TASK_NAME), args=IDS, exception=WorkerLostError("x"))  # pyright: ignore[reportPrivateUsage]
    assert calls.jobs == [(ToolJob(IDS[0], OWNER), FailureReason.WORKER_LOST)] and calls.turns == []


def test_a_job_at_the_hard_limit_is_interrupted_for_the_time_limit(calls: Calls) -> None:
    celery_app._task_failed(_Task(JOB_TASK_NAME), args=IDS, exception=TimeLimitExceeded(960))  # pyright: ignore[reportPrivateUsage]
    assert [reason for _, reason in calls.jobs] == [FailureReason.TIME_LIMIT]


def test_a_lost_turn_task_still_interrupts_its_turn(calls: Calls) -> None:
    celery_app._task_failed(_Task(TASK_NAME), args=IDS, exception=WorkerLostError("x"))  # pyright: ignore[reportPrivateUsage]
    assert calls.turns == [(TurnJob(IDS[0], OWNER), FailureReason.WORKER_LOST)] and calls.jobs == []


@pytest.mark.parametrize(
    ("exception", "args"),
    [
        (RuntimeError("other"), IDS),
        (WorkerLostError("x"), ["bad", "ids"]),
        (WorkerLostError("x"), None),
    ],
)
def test_other_failures_and_bad_arguments_interrupt_nothing(
    calls: Calls,
    exception: BaseException,
    args: list[str] | None,
) -> None:
    celery_app._task_failed(_Task(JOB_TASK_NAME), args=args, exception=exception)  # pyright: ignore[reportPrivateUsage]
    assert calls.jobs == [] and calls.turns == []


def test_the_start_up_sweep_covers_jobs_too(monkeypatch: pytest.MonkeyPatch) -> None:
    swept: list[str] = []

    async def turns(environ: Any) -> int:
        swept.append("turns")
        return 0

    async def jobs(environ: Any) -> int:
        swept.append("jobs")
        return 0

    monkeypatch.setattr(celery_app.recovery, "sweep_stale_env", turns)
    monkeypatch.setattr(celery_app.recovery, "sweep_stale_jobs_env", jobs)
    celery_app._sweep_stale()  # pyright: ignore[reportPrivateUsage]
    assert swept == ["turns", "jobs"]
