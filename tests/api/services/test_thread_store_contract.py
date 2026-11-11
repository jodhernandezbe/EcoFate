"""One contract for every thread store: the in-memory fake and PostgreSQL behave the same.

The fake runs in the default suite; the PostgreSQL run is marked ``postgres`` (make test-db).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import cast
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from api.schemas.workspace import WorkspaceState
from api.services.threads import ThreadStore
from app.usage_meter import CallUsage
from storage.keys import ThreadKey
from storage.turn_model import PlannedInput, Turn, TurnStatus, TurnTransitionError
from tests.fakes import InMemoryThreadStore
from tests.postgres import database
from tools.schemas import ConfirmationRequest

pytestmark = pytest.mark.anyio
THREAD_ID = "contract-thread"
OWNER = UUID(int=1)
OTHER_OWNER = UUID(int=2)
KEY = ThreadKey(OWNER, THREAD_ID)
OTHER_THREAD = ThreadKey(OWNER, "other")
FOREIGN = ThreadKey(OTHER_OWNER, THREAD_ID)  # the same thread id, another user's


@pytest.fixture(params=["fake", pytest.param("postgres", marks=pytest.mark.postgres)])
async def store(request: pytest.FixtureRequest) -> AsyncGenerator[ThreadStore]:
    if request.param == "fake":
        yield InMemoryThreadStore()
        return
    async with database([OWNER, OTHER_OWNER]) as db:
        yield db.store


def _reply(state: MessagesState) -> dict[str, list[AIMessage]]:
    return {"messages": [AIMessage(f"seen {len(state['messages'])}")]}


async def _turn(store: ThreadStore, text: str) -> None:
    await _turn_for(store, KEY, text)


async def _turn_for(store: ThreadStore, key: ThreadKey, text: str) -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("reply", _reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    agent = graph.compile(checkpointer=store.checkpointer)
    await agent.ainvoke(
        {"messages": [HumanMessage(text)]},
        {"configurable": {"thread_id": key.checkpoint_id}},
    )


def _request() -> ConfirmationRequest:
    entry = {
        "entry_id": "rfc:x",
        "quantity": "rfc",
        "subject": "subject-a",
        "accepted_units": ["mg/kg-day"],
        "minimum": 0.001,
        "maximum": 100.0,
        "purpose": "to compute a hazard quotient",
    }
    return cast(ConfirmationRequest, {"request_id": "req-1", "entries": [entry]})


async def test_follow_up_turn_sees_earlier_messages(store: ThreadStore) -> None:
    await _turn(store, "one")
    await _turn(store, "two")
    texts = [m.content for m in await store.messages(KEY)]
    assert texts == ["one", "seen 1", "two", "seen 3"]


async def test_unknown_thread_is_empty(store: ThreadStore) -> None:
    assert not await store.holds(KEY)
    assert await store.messages(KEY) == []
    assert await store.session_calls(KEY) == []
    assert await store.workspace(KEY) is None
    assert await store.pending(KEY) is None
    assert await store.answers(KEY) == ({}, frozenset())


async def test_usage_round_trips_in_order(store: ThreadStore) -> None:
    first = [CallUsage("m", 10, 2, 5), CallUsage("m", None, 0, None)]
    await store.add_usage(KEY, first)
    await store.add_usage(KEY, [CallUsage("n", 1, 0, 1)])
    assert await store.session_calls(KEY) == [*first, CallUsage("n", 1, 0, 1)]


async def test_tool_messages_round_trip_in_order(store: ThreadStore) -> None:
    call = {"name": "lookup", "args": {"q": "x"}, "id": "c1", "type": "tool_call"}
    batch = [AIMessage("", tool_calls=[call]), ToolMessage('{"ok": 1}', tool_call_id="c1")]
    await store.add_tool_messages(KEY, batch)
    await store.add_tool_messages(KEY, [ToolMessage("two", tool_call_id="c2")])
    assert await store.tool_messages(KEY) == [*batch, ToolMessage("two", tool_call_id="c2")]


async def test_workspace_round_trips_and_is_replaced(store: ThreadStore) -> None:
    await store.set_workspace(KEY, WorkspaceState(framing_version=1))
    await store.set_workspace(KEY, WorkspaceState(framing_version=2, warnings=["w"]))
    assert await store.workspace(KEY) == WorkspaceState(framing_version=2, warnings=["w"])


async def test_pending_opens_and_closes(store: ThreadStore) -> None:
    await store.set_pending(KEY, _request())
    assert await store.pending(KEY) == _request()
    await store.set_pending(KEY, None)
    assert await store.pending(KEY) is None
    await store.set_pending(KEY, None)  # closing twice is safe


async def test_supplied_value_is_never_replaced(store: ThreadStore) -> None:
    await store.record_answers(KEY, {"a": 1.5}, ["b"])
    await store.record_answers(KEY, {"a": 9.0, "c": 3.0}, ["a"])
    assert await store.answers(KEY) == ({"a": 1.5, "c": 3.0}, frozenset({"b"}))


async def test_supplied_value_beats_an_earlier_decline(store: ThreadStore) -> None:
    await store.record_answers(KEY, {}, ["a"])
    await store.record_answers(KEY, {"a": 2.0}, [])
    assert await store.answers(KEY) == ({"a": 2.0}, frozenset())


async def test_claim_twice_refuses_the_second(store: ThreadStore) -> None:
    assert await store.claim(KEY)
    assert await store.running(KEY)
    assert not await store.claim(KEY)
    await store.release(KEY)
    assert await store.claim(KEY)


async def test_release_twice_is_safe(store: ThreadStore) -> None:
    await store.claim(KEY)
    await store.release(KEY)
    await store.release(KEY)
    await store.release(ThreadKey(OWNER, "never-claimed"))
    assert not await store.running(KEY)
    assert await store.holds(KEY)


async def test_touch_creates_the_thread(store: ThreadStore) -> None:
    await store.touch(KEY)
    assert await store.holds(KEY)
    assert not await store.running(KEY)


async def _fill(store: ThreadStore) -> None:
    await _turn(store, "one")
    await store.add_usage(KEY, [CallUsage("m", 1, 0, 1)])
    await store.add_tool_messages(KEY, [ToolMessage("r", tool_call_id="c")])
    await store.set_workspace(KEY, WorkspaceState(framing_version=3))
    await store.set_pending(KEY, _request())
    await store.record_answers(KEY, {"a": 1.0}, ["b"])


async def test_reset_clears_everything(store: ThreadStore) -> None:
    await _fill(store)
    assert await store.reset(KEY)
    assert not await store.holds(KEY)
    assert await store.messages(KEY) == []
    assert await store.session_calls(KEY) == []
    assert await store.tool_messages(KEY) == []
    assert await store.workspace(KEY) is None
    assert await store.pending(KEY) is None
    assert await store.answers(KEY) == ({}, frozenset())


async def test_reset_refuses_while_busy(store: ThreadStore) -> None:
    await _fill(store)
    await store.claim(KEY)
    assert not await store.reset(KEY)
    assert await store.workspace(KEY) == WorkspaceState(framing_version=3)
    assert len(await store.messages(KEY)) == 2


async def test_threads_are_independent(store: ThreadStore) -> None:
    await store.claim(KEY)
    await store.record_answers(KEY, {"a": 1.0}, [])
    assert await store.claim(OTHER_THREAD)
    assert await store.answers(OTHER_THREAD) == ({}, frozenset())


# --- turns ----------------------------------------------------------------------------------


async def _interrupted(store: ThreadStore, reason: str = "out_of_credits") -> str:
    turn = await store.turns.begin(KEY)
    assert turn is not None
    await store.turns.move(OWNER, turn.id, TurnStatus.INTERRUPTED, reason)
    return turn.id


async def _running(store: ThreadStore, key: ThreadKey = KEY) -> Turn:
    queued = await store.turns.begin(key)
    assert queued is not None
    started = await store.turns.start(key.owner_id, queued.id)
    assert started is not None
    return started


async def test_a_turn_is_queued_runs_then_completes_with_its_times(store: ThreadStore) -> None:
    queued = await store.turns.begin(KEY)
    assert queued is not None
    assert (queued.status, queued.reason, queued.resume_count) == (TurnStatus.QUEUED, None, 0)
    assert queued.started_at is None and queued.heartbeat_at is None
    turn = await store.turns.start(OWNER, queued.id)
    assert turn is not None and turn.status is TurnStatus.RUNNING
    assert turn.started_at is not None and turn.finished_at is None
    assert turn.heartbeat_at is not None
    done = await store.turns.move(OWNER, turn.id, TurnStatus.COMPLETED)
    assert done.status is TurnStatus.COMPLETED and done.finished_at is not None
    assert await store.turns.latest(KEY) == done


async def test_a_second_open_turn_on_the_thread_is_refused(store: ThreadStore) -> None:
    first = await store.turns.begin(KEY)
    assert first is not None
    assert await store.turns.begin(KEY) is None
    assert await store.turns.latest(KEY) == first
    assert await store.turns.begin(OTHER_THREAD) is not None  # other threads are independent


async def test_completed_cannot_run_again_and_is_left_unchanged(store: ThreadStore) -> None:
    turn = await _running(store)
    done = await store.turns.move(OWNER, turn.id, TurnStatus.COMPLETED)
    with pytest.raises(TurnTransitionError):
        await store.turns.move(OWNER, turn.id, TurnStatus.RUNNING)
    assert await store.turns.resume(OWNER, turn.id, 3) is None
    assert await store.turns.latest(KEY) == done


async def test_an_unknown_turn_cannot_move(store: ThreadStore) -> None:
    with pytest.raises(TurnTransitionError):
        await store.turns.move(OWNER, "no-such-turn", TurnStatus.COMPLETED)


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        (TurnStatus.INTERRUPTED, None),
        (TurnStatus.FAILED, None),
        (TurnStatus.COMPLETED, "out_of_credits"),
    ],
)
async def test_a_reason_must_fit_the_status(
    store: ThreadStore,
    target: TurnStatus,
    reason: str | None,
) -> None:
    turn = await store.turns.begin(KEY)
    assert turn is not None
    with pytest.raises(ValueError, match="reason"):
        await store.turns.move(OWNER, turn.id, target, reason)
    assert await store.turns.latest(KEY) == turn


async def test_resume_counts_each_time_up_to_the_cap(store: ThreadStore) -> None:
    turn_id = await _interrupted(store)
    for expected in (1, 2):
        resumed = await store.turns.resume(OWNER, turn_id, 2)
        assert resumed is not None
        assert (resumed.status, resumed.reason, resumed.resume_count) == (
            TurnStatus.QUEUED,
            None,
            expected,
        )
        await store.turns.move(OWNER, turn_id, TurnStatus.INTERRUPTED, "rate_limited")
    assert await store.turns.resume(OWNER, turn_id, 2) is None
    stays = await store.turns.latest(KEY)
    assert stays is not None
    assert (stays.status, stays.reason, stays.resume_count) == (
        TurnStatus.INTERRUPTED,
        "rate_limited",
        2,
    )


async def test_resume_is_refused_while_another_turn_of_the_thread_is_open(
    store: ThreadStore,
) -> None:
    turn_id = await _interrupted(store)
    other = await store.turns.begin(KEY)
    assert other is not None
    assert await store.turns.resume(OWNER, turn_id, 3) is None
    assert await store.turns.latest(KEY) == other


async def test_an_interrupted_turn_can_be_abandoned_or_found_finished(store: ThreadStore) -> None:
    turn_id = await _interrupted(store)
    failed = await store.turns.move(OWNER, turn_id, TurnStatus.FAILED, "superseded")
    assert (failed.status, failed.reason) == (TurnStatus.FAILED, "superseded")
    assert failed.finished_at is not None
    second = await _interrupted(store)
    done = await store.turns.move(OWNER, second, TurnStatus.COMPLETED)
    assert (done.status, done.reason) == (TurnStatus.COMPLETED, None)


async def test_abandon_interrupts_only_an_open_turn_and_is_safe_to_repeat(
    store: ThreadStore,
) -> None:
    turn = await store.turns.begin(KEY)
    assert turn is not None
    assert await store.turns.abandon(OWNER, turn.id, "worker_lost")
    assert not await store.turns.abandon(OWNER, turn.id, "worker_lost")
    assert not await store.turns.abandon(OWNER, "no-such-turn", "worker_lost")
    latest = await store.turns.latest(KEY)
    assert latest is not None
    assert (latest.status, latest.reason) == (TurnStatus.INTERRUPTED, "worker_lost")


async def test_interrupt_open_frees_one_thread_or_every_users_thread(store: ThreadStore) -> None:
    assert await store.turns.begin(KEY) is not None
    assert await store.turns.begin(OTHER_THREAD) is not None
    assert await store.turns.begin(FOREIGN) is not None
    await store.turns.interrupt_open(OTHER_THREAD, "worker_lost")
    assert set(await store.turns.interrupt_all_open("worker_lost")) == {KEY, FOREIGN}
    assert await store.turns.interrupt_all_open("worker_lost") == []
    for key in (KEY, OTHER_THREAD, FOREIGN):
        latest = await store.turns.latest(key)
        assert latest is not None and latest.status is TurnStatus.INTERRUPTED
        assert await store.turns.begin(key) is not None


async def test_usage_is_kept_per_turn(store: ThreadStore) -> None:
    turn = await store.turns.begin(KEY)
    assert turn is not None
    await store.add_usage(KEY, [CallUsage("m", 1, 0, 1)], turn.id)
    await store.add_usage(KEY, [CallUsage("m", 2, 0, 2)])
    await store.add_usage(KEY, [CallUsage("m", 3, 0, 3)], turn.id)
    expected = [CallUsage("m", 1, 0, 1), CallUsage("m", 3, 0, 3)]
    assert await store.turn_calls(KEY, turn.id) == expected
    assert len(await store.session_calls(KEY)) == 3


async def test_a_new_turn_keeps_its_planned_input(store: ThreadStore) -> None:
    planned = PlannedInput("question", "message", "note", counted=True)
    turn = await store.turns.begin(KEY, planned)
    assert turn is not None and turn.planned == planned
    assert await store.turns.get(OWNER, turn.id) == turn
    assert await store.turns.get(OTHER_OWNER, turn.id) is None
    assert await store.turns.get(OWNER, "no-such-turn") is None


async def test_a_queued_turn_starts_once(store: ThreadStore) -> None:
    turn = await _running(store)
    assert await store.turns.start(OWNER, turn.id) is None  # a second delivery does nothing
    await store.turns.move(OWNER, turn.id, TurnStatus.COMPLETED)
    assert await store.turns.start(OWNER, turn.id) is None


async def test_another_user_cannot_start_a_queued_turn(store: ThreadStore) -> None:
    queued = await store.turns.begin(KEY)
    assert queued is not None
    assert await store.turns.start(OTHER_OWNER, queued.id) is None
    assert await store.turns.latest(KEY) == queued


async def test_a_resumed_turn_waits_queued_with_a_fresh_cancel_flag(store: ThreadStore) -> None:
    turn = await _running(store)
    assert await store.turns.request_cancel(OWNER, turn.id)
    await store.turns.move(OWNER, turn.id, TurnStatus.INTERRUPTED, "cancelled")
    resumed = await store.turns.resume(OWNER, turn.id, 3)
    assert resumed is not None and resumed.status is TurnStatus.QUEUED
    assert not resumed.cancel_requested and resumed.heartbeat_at is None


async def test_a_queued_turn_that_could_not_be_enqueued_fails(store: ThreadStore) -> None:
    queued = await store.turns.begin(KEY)
    assert queued is not None
    failed = await store.turns.move(OWNER, queued.id, TurnStatus.FAILED, "unexpected")
    assert failed.status is TurnStatus.FAILED and failed.finished_at is not None


async def test_heartbeat_only_for_a_running_turn(store: ThreadStore) -> None:
    queued = await store.turns.begin(KEY)
    assert queued is not None
    assert not await store.turns.heartbeat(OWNER, queued.id)
    await store.turns.start(OWNER, queued.id)
    assert await store.turns.heartbeat(OWNER, queued.id)
    assert not await store.turns.heartbeat(OTHER_OWNER, queued.id)
    await store.turns.move(OWNER, queued.id, TurnStatus.COMPLETED)
    assert not await store.turns.heartbeat(OWNER, queued.id)


async def test_cancel_is_asked_only_of_an_open_turn_of_the_owner(store: ThreadStore) -> None:
    turn = await _running(store)
    assert not await store.turns.request_cancel(OTHER_OWNER, turn.id)
    assert not await store.turns.cancel_requested(OWNER, turn.id)
    assert await store.turns.request_cancel(OWNER, turn.id)
    assert await store.turns.request_cancel(OWNER, turn.id)  # safe to repeat
    assert await store.turns.cancel_requested(OWNER, turn.id)
    assert not await store.turns.cancel_requested(OTHER_OWNER, turn.id)
    await store.turns.move(OWNER, turn.id, TurnStatus.INTERRUPTED, "cancelled")
    assert not await store.turns.request_cancel(OWNER, turn.id)


async def test_only_a_stale_running_turn_is_interrupted(store: ThreadStore) -> None:
    running = await _running(store)
    queued = await store.turns.begin(OTHER_THREAD)
    assert queued is not None
    assert await store.turns.interrupt_stale(timedelta(hours=1), "worker_lost") == []
    assert await store.turns.interrupt_stale(timedelta(0), "worker_lost", FOREIGN) == []
    assert await store.turns.interrupt_stale(timedelta(0), "worker_lost") == [KEY]
    stale = await store.turns.get(OWNER, running.id)
    assert stale is not None
    assert (stale.status, stale.reason) == (TurnStatus.INTERRUPTED, "worker_lost")
    assert await store.turns.get(OWNER, queued.id) == queued  # waiting is not stale


async def test_queue_position_counts_earlier_queued_turns(store: ThreadStore) -> None:
    first = await store.turns.begin(KEY)
    second = await store.turns.begin(FOREIGN)
    third = await store.turns.begin(OTHER_THREAD)
    assert first is not None and second is not None and third is not None
    assert await store.turns.queue_position(first.id) == 0
    assert await store.turns.queue_position(third.id) == 2
    await store.turns.start(OWNER, first.id)
    assert await store.turns.queue_position(third.id) == 1


async def test_extend_renews_a_held_lease_only(store: ThreadStore) -> None:
    await store.extend(KEY)
    assert not await store.running(KEY)  # an idle thread stays idle
    assert await store.claim(KEY)
    await store.extend(KEY)
    assert await store.running(KEY)
    await store.release(KEY)
    await store.extend(KEY)
    assert not await store.running(KEY)


async def test_the_latest_thread_is_the_owners_most_recently_used(store: ThreadStore) -> None:
    assert await store.latest_thread(OWNER) is None
    await store.touch(KEY)
    await asyncio.sleep(0.002)  # distinct use times
    await store.touch(OTHER_THREAD)
    assert await store.latest_thread(OWNER) == OTHER_THREAD.thread_id
    await asyncio.sleep(0.002)
    await store.touch(KEY)
    assert await store.latest_thread(OWNER) == KEY.thread_id
    assert await store.latest_thread(OTHER_OWNER) is None  # never another user's
    await store.touch(FOREIGN)
    assert await store.latest_thread(OWNER) == KEY.thread_id


async def test_reset_deletes_the_threads_turns(store: ThreadStore) -> None:
    await _interrupted(store)
    assert await store.reset(KEY)
    assert await store.turns.latest(KEY) is None


# --- ownership: the same thread id of another user is another thread -------------------------


async def _fill_for(store: ThreadStore, key: ThreadKey, marker: float) -> None:
    await store.add_usage(key, [CallUsage("m", 1, 0, 1)])
    await store.add_tool_messages(key, [ToolMessage(f"tool-{marker}", tool_call_id="c")])
    await store.set_workspace(key, WorkspaceState(framing_version=int(marker)))
    await store.set_pending(key, _request())
    await store.record_answers(key, {"a": marker}, ["b"])


async def test_another_users_thread_is_not_found(store: ThreadStore) -> None:
    await _fill(store)
    assert not await store.holds(FOREIGN)
    assert not await store.running(FOREIGN)
    assert await store.messages(FOREIGN) == []
    assert await store.session_calls(FOREIGN) == []
    assert await store.tool_messages(FOREIGN) == []
    assert await store.workspace(FOREIGN) is None
    assert await store.pending(FOREIGN) is None
    assert await store.answers(FOREIGN) == ({}, frozenset())
    assert await store.turns.latest(FOREIGN) is None


async def test_the_same_thread_id_of_two_users_stays_separate(store: ThreadStore) -> None:
    await _fill_for(store, KEY, 1.0)
    await _fill_for(store, FOREIGN, 2.0)
    assert await store.answers(KEY) == ({"a": 1.0}, frozenset({"b"}))
    assert await store.answers(FOREIGN) == ({"a": 2.0}, frozenset({"b"}))
    assert await store.workspace(KEY) == WorkspaceState(framing_version=1)
    assert await store.workspace(FOREIGN) == WorkspaceState(framing_version=2)
    assert [m.content for m in await store.tool_messages(KEY)] == ["tool-1.0"]
    assert [m.content for m in await store.tool_messages(FOREIGN)] == ["tool-2.0"]
    assert len(await store.session_calls(KEY)) == len(await store.session_calls(FOREIGN)) == 1


async def test_two_users_have_separate_checkpoints_for_the_same_thread_id(
    store: ThreadStore,
) -> None:
    await _turn(store, "mine")
    await _turn_for(store, FOREIGN, "theirs")
    assert [m.content for m in await store.messages(KEY)] == ["mine", "seen 1"]
    assert [m.content for m in await store.messages(FOREIGN)] == ["theirs", "seen 1"]


async def test_a_lease_is_per_owner(store: ThreadStore) -> None:
    assert await store.claim(KEY)
    assert await store.claim(FOREIGN)  # not refused: another user's thread
    await store.release(FOREIGN)
    assert await store.running(KEY)
    assert not await store.running(FOREIGN)
    assert not await store.claim(KEY)


async def test_releasing_another_users_thread_does_not_free_it(store: ThreadStore) -> None:
    assert await store.claim(KEY)
    await store.release(FOREIGN)
    assert await store.running(KEY)


async def test_reset_by_another_user_changes_nothing(store: ThreadStore) -> None:
    await _fill(store)
    assert await store.reset(FOREIGN)  # nothing of theirs to delete
    assert await store.holds(KEY)
    assert len(await store.messages(KEY)) == 2
    assert await store.workspace(KEY) == WorkspaceState(framing_version=3)


async def test_one_user_cannot_move_or_resume_anothers_turn(store: ThreadStore) -> None:
    turn_id = await _interrupted(store)
    with pytest.raises(TurnTransitionError):
        await store.turns.move(OTHER_OWNER, turn_id, TurnStatus.COMPLETED)
    assert await store.turns.resume(OTHER_OWNER, turn_id, 3) is None
    assert not await store.turns.abandon(OTHER_OWNER, turn_id, "worker_lost")
    latest = await store.turns.latest(KEY)
    assert latest is not None and latest.status is TurnStatus.INTERRUPTED


async def test_each_user_has_one_open_turn_per_thread_id(store: ThreadStore) -> None:
    assert await store.turns.begin(KEY) is not None
    assert await store.turns.begin(FOREIGN) is not None
    assert await store.turns.begin(KEY) is None
    assert await store.turns.begin(FOREIGN) is None


async def test_forget_owner_deletes_only_that_users_threads(store: ThreadStore) -> None:
    await _fill(store)
    await _fill_for(store, OTHER_THREAD, 5.0)
    await _fill_for(store, FOREIGN, 2.0)
    await _turn_for(store, FOREIGN, "theirs")
    assert await store.forget_owner(OTHER_OWNER) == 1
    assert not await store.holds(FOREIGN)
    assert await store.messages(FOREIGN) == []
    assert await store.turns.latest(FOREIGN) is None
    assert await store.holds(KEY) and await store.holds(OTHER_THREAD)
    assert await store.forget_owner(OTHER_OWNER) == 0


async def test_forget_owner_deletes_a_running_thread_too(store: ThreadStore) -> None:
    await store.claim(KEY)
    assert await store.forget_owner(OWNER) == 1
    assert not await store.holds(KEY)


async def test_purge_idle_reports_the_owner_and_thread(store: ThreadStore) -> None:
    await store.touch(KEY)
    await store.touch(FOREIGN)
    purged = await store.purge_idle(timedelta(seconds=-1))
    assert set(purged) == {KEY, FOREIGN}
