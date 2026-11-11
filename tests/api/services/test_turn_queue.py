"""Submitting a turn: its first record, its task message (ids only) and a queue that is down."""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID

import pytest
from celery.signals import before_task_publish

from api.main import queue_setup
from api.services.turn_queue import QueueUnavailableError, TurnQueue, submit
from app.task_queue import CeleryEnqueuer, EnqueueError, TurnJob, build_celery
from app.turns.bus import MemoryBus, turn_stream
from app.turns.codec import TurnQueued, decode
from config.worker import get_worker_settings
from storage.turn_model import PlannedInput, Turn, TurnStatus
from tests.api.keys import OWNER, owned
from tests.fakes import InMemoryThreadStore

pytestmark = pytest.mark.anyio
KEY = "sk-proj-" + "s0U1b2M3i4" * 3  # pragma: allowlist secret
COOKIE = "session-" + "c0O1k2I3e4" * 3  # pragma: allowlist secret
MESSAGE = "Assess formaldehyde for my neighbours"


class DownBroker:
    async def enqueue(self, job: TurnJob) -> None:
        raise EnqueueError("ConnectionError")


@pytest.fixture
def published() -> Iterator[list[tuple[object, object]]]:
    seen: list[tuple[object, object]] = []

    def capture(body: object = None, headers: object = None, **_: object) -> None:
        seen.append((body, headers))

    before_task_publish.connect(capture, weak=False)
    yield seen
    before_task_publish.disconnect(capture)


def _queue(enqueuer: object) -> TurnQueue:
    setup = queue_setup(MemoryBus(), None)
    return TurnQueue(setup.bus, enqueuer, setup.timing, setup.background)  # type: ignore[arg-type]


async def _queued(threads: InMemoryThreadStore, counted: bool = True) -> Turn:
    assert await threads.claim(owned("s1"))
    turn = await threads.turns.begin(owned("s1"), PlannedInput(MESSAGE, MESSAGE, "", counted))
    assert turn is not None
    return turn


async def test_the_queued_record_comes_first_with_the_position(
    published: list[tuple[object, object]],
) -> None:
    threads = InMemoryThreadStore()
    settings = get_worker_settings()
    queue = _queue(CeleryEnqueuer(build_celery(settings, "memory://"), settings, [KEY, COOKIE]))
    turn = await _queued(threads)
    await submit(turn, queue, threads, None)
    ((seq, record),) = await queue.bus.read(turn_stream(turn.id, 0), None, 0.01)
    assert (seq, decode(record)) == (0, TurnQueued(0))
    ((body, headers),) = published
    serialized = json.dumps([body, headers], default=str)
    assert turn.id in serialized and str(OWNER) in serialized
    for secret in (KEY, COOKIE, MESSAGE, "formaldehyde"):
        assert secret not in serialized


async def test_a_queue_that_is_down_fails_a_new_turn_and_gives_it_back() -> None:
    threads = InMemoryThreadStore()
    refunds: list[tuple[UUID, str]] = []

    async def refund(user_id: UUID, turn_id: str) -> bool:
        refunds.append((user_id, turn_id))
        return True

    turn = await _queued(threads)
    with pytest.raises(QueueUnavailableError):
        await submit(turn, _queue(DownBroker()), threads, refund)
    failed = await threads.turns.get(OWNER, turn.id)
    assert failed is not None and (failed.status, failed.reason) == (
        TurnStatus.FAILED,
        "unexpected",
    )
    assert refunds == [(OWNER, turn.id)]
    assert not await threads.running(owned("s1"))


async def test_a_resume_that_cannot_be_queued_stays_resumable() -> None:
    threads = InMemoryThreadStore()
    turn = await _queued(threads, counted=False)
    await threads.turns.start(OWNER, turn.id)
    await threads.turns.move(OWNER, turn.id, TurnStatus.INTERRUPTED, "rate_limited")
    resumed = await threads.turns.resume(OWNER, turn.id, 3)
    assert resumed is not None
    with pytest.raises(QueueUnavailableError):
        await submit(resumed, _queue(DownBroker()), threads, None)
    again = await threads.turns.get(OWNER, turn.id)
    assert again is not None and (again.status, again.reason) == (
        TurnStatus.INTERRUPTED,
        "worker_lost",
    )
