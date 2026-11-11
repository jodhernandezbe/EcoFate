"""The worker's task and its queue settings: ids only, eager in-process, malformed messages."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import cast
from uuid import UUID

import pytest
from celery.result import EagerResult
from celery.signals import before_task_publish

from app.task_queue import (
    TASK_NAME,
    BrokerSetupError,
    CeleryEnqueuer,
    EnqueueError,
    InProcessEnqueuer,
    TurnJob,
    build_celery,
    redis_url,
)
from commons.payload_guard import PayloadRefusedError
from config.worker import get_worker_settings
from worker.celery_app import ChildRunner, celery, child_runtime, install_child_runtime
from worker.tasks import run_turn_task

pytestmark = pytest.mark.anyio
OWNER = UUID(int=7)
TURN = "b" * 32
KEY = "sk-proj-" + "w0R1k2E3r4" * 3  # pragma: allowlist secret


class Recorder:
    """A child runtime that records the jobs it is given."""

    def __init__(self) -> None:
        self.jobs: list[TurnJob] = []

    def run(self, job: TurnJob) -> None:
        self.jobs.append(job)

    def close(self) -> None:
        pass


@pytest.fixture
def child() -> Iterator[Recorder]:
    recorder = Recorder()
    runner: ChildRunner = recorder
    install_child_runtime(runner)
    yield recorder
    install_child_runtime(None)


@pytest.fixture
def published() -> Iterator[list[tuple[object, object]]]:
    seen: list[tuple[object, object]] = []

    def capture(body: object = None, headers: object = None, **_: object) -> None:
        seen.append((body, headers))

    before_task_publish.connect(capture, weak=False)
    yield seen
    before_task_publish.disconnect(capture)


def test_the_queue_settings_never_rerun_a_lost_turn() -> None:
    settings = get_worker_settings()
    conf = cast(Mapping[str, object], celery.conf)  # Celery's settings are untyped
    assert conf["task_acks_late"] is True
    assert conf["task_reject_on_worker_lost"] is False
    assert conf["worker_prefetch_multiplier"] == settings.prefetch_multiplier
    assert conf["task_time_limit"] == settings.time_limit_seconds
    assert conf["task_default_queue"] == settings.queue
    visibility = cast(Mapping[str, object], conf["broker_transport_options"])["visibility_timeout"]
    assert visibility == settings.visibility_timeout_seconds > settings.time_limit_seconds
    assert TASK_NAME in celery.tasks


async def test_the_serialized_task_message_carries_the_ids_only(
    published: list[tuple[object, object]],
) -> None:
    settings = get_worker_settings()
    enqueuer = CeleryEnqueuer(build_celery(settings, "memory://"), settings, protected=[KEY])
    await enqueuer.enqueue(TurnJob(TURN, OWNER))
    ((body, headers),) = published
    serialized = json.dumps([body, headers], default=str)
    assert TURN in serialized and str(OWNER) in serialized
    assert KEY not in serialized
    args, kwargs, _ = body  # type: ignore[misc]
    assert args == [TURN, str(OWNER)] and kwargs == {}


async def test_a_payload_carrying_a_secret_is_refused_before_it_is_sent(
    published: list[tuple[object, object]],
) -> None:
    settings = get_worker_settings()
    enqueuer = CeleryEnqueuer(build_celery(settings, "memory://"), settings, protected=[TURN])
    with pytest.raises(PayloadRefusedError):
        await enqueuer.enqueue(TurnJob(TURN, OWNER))
    assert published == []


async def test_an_unreachable_broker_fails_the_enqueue_in_time() -> None:
    settings = replace(get_worker_settings(), broker_timeout_seconds=1)
    app = build_celery(settings, "redis://127.0.0.1:1/0")
    with pytest.raises(EnqueueError):
        await CeleryEnqueuer(app, settings).enqueue(TurnJob(TURN, OWNER))


async def test_the_in_process_enqueuer_runs_the_job_in_the_background() -> None:
    ran: list[TurnJob] = []

    async def job(found: TurnJob) -> None:
        ran.append(found)

    enqueuer = InProcessEnqueuer(job)
    await enqueuer.enqueue(TurnJob(TURN, OWNER))
    await enqueuer.drain()
    assert ran == [TurnJob(TURN, OWNER)]


def test_the_task_runs_eagerly_on_the_child_runtime(child: Recorder) -> None:
    result = cast(EagerResult, run_turn_task.apply(args=[TURN, str(OWNER)]))  # pyright: ignore[reportUnknownMemberType]
    assert result.successful()
    assert child.jobs == [TurnJob(TURN, OWNER)]


@pytest.mark.parametrize(
    "args",
    [["not-a-turn", str(OWNER)], [TURN, "not-a-uuid"], [TURN.upper(), str(OWNER)], [3, str(OWNER)]],
)
def test_a_malformed_task_message_runs_nothing(child: Recorder, args: list[object]) -> None:
    result = cast(EagerResult, run_turn_task.apply(args=args))  # pyright: ignore[reportUnknownMemberType]
    assert result.failed()
    assert child.jobs == []


def test_a_child_without_a_runtime_refuses_to_run() -> None:
    install_child_runtime(None)
    with pytest.raises(RuntimeError, match="no runtime"):
        child_runtime()


def test_the_redis_url_must_be_set() -> None:
    settings = get_worker_settings()
    with pytest.raises(BrokerSetupError, match=settings.redis_url_env_var):
        redis_url({}, settings)
    assert (
        redis_url({settings.redis_url_env_var: " redis://r:6379/0 "}, settings)
        == "redis://r:6379/0"
    )
