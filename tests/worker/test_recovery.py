"""Lost and stale turns become resumable; nothing is re-run."""

from __future__ import annotations

from datetime import timedelta

import pytest
from celery.exceptions import TimeLimitExceeded, WorkerLostError

from app.task_queue import TurnJob
from app.turns.failures import FailureReason
from storage.keys import ThreadKey
from storage.turn_model import TurnStatus
from tests.fakes import OWNER_ID, InMemoryThreadStore
from worker.recovery import interrupt_lost, job_of, lost_reason, sweep_stale

pytestmark = pytest.mark.anyio
KEY = ThreadKey(OWNER_ID, "lost")


async def _running(store: InMemoryThreadStore) -> str:
    assert await store.claim(KEY)
    turn = await store.turns.begin(KEY)
    assert turn is not None
    assert await store.turns.start(OWNER_ID, turn.id) is not None
    return turn.id


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (WorkerLostError("lost"), FailureReason.WORKER_LOST),
        (TimeLimitExceeded(960), FailureReason.TIME_LIMIT),
        (RuntimeError("other"), None),
        (None, None),
    ],
)
def test_only_a_lost_child_or_the_hard_limit_interrupts(
    exception: BaseException | None,
    reason: FailureReason | None,
) -> None:
    assert lost_reason(exception) == reason


@pytest.mark.parametrize(
    "args",
    [None, [], ["a" * 32], ["a" * 32, str(OWNER_ID), "x"], ["../x", str(OWNER_ID)], [1, 2]],
)
def test_task_arguments_that_do_not_fit_name_no_job(args: list[object] | None) -> None:
    assert job_of(args) is None


def test_task_arguments_name_their_job() -> None:
    assert job_of(("a" * 32, str(OWNER_ID))) == TurnJob("a" * 32, OWNER_ID)


async def test_a_lost_turn_is_interrupted_and_its_thread_released() -> None:
    store = InMemoryThreadStore()
    turn_id = await _running(store)
    job = TurnJob(turn_id, OWNER_ID)
    assert await interrupt_lost(store.turns, store.release, job, FailureReason.WORKER_LOST)
    turn = await store.turns.get(OWNER_ID, turn_id)
    assert turn is not None and (turn.status, turn.reason) == (
        TurnStatus.INTERRUPTED,
        "worker_lost",
    )
    assert not await store.running(KEY)


async def test_a_turn_that_already_ended_is_left_alone() -> None:
    store = InMemoryThreadStore()
    turn_id = await _running(store)
    await store.turns.move(OWNER_ID, turn_id, TurnStatus.COMPLETED)
    second = await store.turns.begin(ThreadKey(OWNER_ID, "other"))
    assert second is not None
    job = TurnJob(turn_id, OWNER_ID)
    assert not await interrupt_lost(store.turns, store.release, job, FailureReason.WORKER_LOST)
    assert await store.running(KEY)  # the lease of whatever runs now is untouched


async def test_the_start_up_sweep_interrupts_only_stale_turns() -> None:
    store = InMemoryThreadStore()
    turn_id = await _running(store)
    assert await sweep_stale(store.turns, store.release, timedelta(hours=1)) == 0
    assert await sweep_stale(store.turns, store.release, timedelta(0)) == 1
    turn = await store.turns.get(OWNER_ID, turn_id)
    assert turn is not None and turn.reason == "worker_lost"
    assert not await store.running(KEY)
