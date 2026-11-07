"""One contract for every thread store: the in-memory fake and PostgreSQL behave the same.

The fake runs in the default suite; the PostgreSQL run is marked ``postgres`` (make test-db).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from api.schemas.workspace import WorkspaceState
from api.services.threads import ThreadStore
from app.usage_meter import CallUsage
from storage.turn_model import TurnStatus, TurnTransitionError
from tests.fakes import InMemoryThreadStore
from tests.postgres import database
from tools.schemas import ConfirmationRequest

pytestmark = pytest.mark.anyio
THREAD = "contract-thread"


@pytest.fixture(params=["fake", pytest.param("postgres", marks=pytest.mark.postgres)])
async def store(request: pytest.FixtureRequest) -> AsyncGenerator[ThreadStore]:
    if request.param == "fake":
        yield InMemoryThreadStore()
        return
    async with database() as db:
        yield db.store


def _reply(state: MessagesState) -> dict[str, list[AIMessage]]:
    return {"messages": [AIMessage(f"seen {len(state['messages'])}")]}


async def _turn(store: ThreadStore, text: str) -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("reply", _reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    agent = graph.compile(checkpointer=store.checkpointer)
    await agent.ainvoke({"messages": [HumanMessage(text)]}, {"configurable": {"thread_id": THREAD}})


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
    texts = [m.content for m in await store.messages(THREAD)]
    assert texts == ["one", "seen 1", "two", "seen 3"]


async def test_unknown_thread_is_empty(store: ThreadStore) -> None:
    assert not await store.holds(THREAD)
    assert await store.messages(THREAD) == []
    assert await store.session_calls(THREAD) == []
    assert await store.workspace(THREAD) is None
    assert await store.pending(THREAD) is None
    assert await store.answers(THREAD) == ({}, frozenset())


async def test_usage_round_trips_in_order(store: ThreadStore) -> None:
    first = [CallUsage("m", 10, 2, 5), CallUsage("m", None, 0, None)]
    await store.add_usage(THREAD, first)
    await store.add_usage(THREAD, [CallUsage("n", 1, 0, 1)])
    assert await store.session_calls(THREAD) == [*first, CallUsage("n", 1, 0, 1)]


async def test_tool_messages_round_trip_in_order(store: ThreadStore) -> None:
    call = {"name": "lookup", "args": {"q": "x"}, "id": "c1", "type": "tool_call"}
    batch = [AIMessage("", tool_calls=[call]), ToolMessage('{"ok": 1}', tool_call_id="c1")]
    await store.add_tool_messages(THREAD, batch)
    await store.add_tool_messages(THREAD, [ToolMessage("two", tool_call_id="c2")])
    assert await store.tool_messages(THREAD) == [*batch, ToolMessage("two", tool_call_id="c2")]


async def test_workspace_round_trips_and_is_replaced(store: ThreadStore) -> None:
    await store.set_workspace(THREAD, WorkspaceState(framing_version=1))
    await store.set_workspace(THREAD, WorkspaceState(framing_version=2, warnings=["w"]))
    assert await store.workspace(THREAD) == WorkspaceState(framing_version=2, warnings=["w"])


async def test_pending_opens_and_closes(store: ThreadStore) -> None:
    await store.set_pending(THREAD, _request())
    assert await store.pending(THREAD) == _request()
    await store.set_pending(THREAD, None)
    assert await store.pending(THREAD) is None
    await store.set_pending(THREAD, None)  # closing twice is safe


async def test_supplied_value_is_never_replaced(store: ThreadStore) -> None:
    await store.record_answers(THREAD, {"a": 1.5}, ["b"])
    await store.record_answers(THREAD, {"a": 9.0, "c": 3.0}, ["a"])
    assert await store.answers(THREAD) == ({"a": 1.5, "c": 3.0}, frozenset({"b"}))


async def test_supplied_value_beats_an_earlier_decline(store: ThreadStore) -> None:
    await store.record_answers(THREAD, {}, ["a"])
    await store.record_answers(THREAD, {"a": 2.0}, [])
    assert await store.answers(THREAD) == ({"a": 2.0}, frozenset())


async def test_claim_twice_refuses_the_second(store: ThreadStore) -> None:
    assert await store.claim(THREAD)
    assert await store.running(THREAD)
    assert not await store.claim(THREAD)
    await store.release(THREAD)
    assert await store.claim(THREAD)


async def test_release_twice_is_safe(store: ThreadStore) -> None:
    await store.claim(THREAD)
    await store.release(THREAD)
    await store.release(THREAD)
    await store.release("never-claimed")
    assert not await store.running(THREAD)
    assert await store.holds(THREAD)


async def test_touch_creates_the_thread(store: ThreadStore) -> None:
    await store.touch(THREAD)
    assert await store.holds(THREAD)
    assert not await store.running(THREAD)


async def _fill(store: ThreadStore) -> None:
    await _turn(store, "one")
    await store.add_usage(THREAD, [CallUsage("m", 1, 0, 1)])
    await store.add_tool_messages(THREAD, [ToolMessage("r", tool_call_id="c")])
    await store.set_workspace(THREAD, WorkspaceState(framing_version=3))
    await store.set_pending(THREAD, _request())
    await store.record_answers(THREAD, {"a": 1.0}, ["b"])


async def test_reset_clears_everything(store: ThreadStore) -> None:
    await _fill(store)
    assert await store.reset(THREAD)
    assert not await store.holds(THREAD)
    assert await store.messages(THREAD) == []
    assert await store.session_calls(THREAD) == []
    assert await store.tool_messages(THREAD) == []
    assert await store.workspace(THREAD) is None
    assert await store.pending(THREAD) is None
    assert await store.answers(THREAD) == ({}, frozenset())


async def test_reset_refuses_while_busy(store: ThreadStore) -> None:
    await _fill(store)
    await store.claim(THREAD)
    assert not await store.reset(THREAD)
    assert await store.workspace(THREAD) == WorkspaceState(framing_version=3)
    assert len(await store.messages(THREAD)) == 2


async def test_threads_are_independent(store: ThreadStore) -> None:
    await store.claim(THREAD)
    await store.record_answers(THREAD, {"a": 1.0}, [])
    assert await store.claim("other")
    assert await store.answers("other") == ({}, frozenset())


# --- turns ----------------------------------------------------------------------------------


async def _interrupted(store: ThreadStore, reason: str = "out_of_credits") -> str:
    turn = await store.turns.begin(THREAD)
    assert turn is not None
    await store.turns.move(turn.id, TurnStatus.INTERRUPTED, reason)
    return turn.id


async def test_a_turn_runs_then_completes_with_its_times(store: ThreadStore) -> None:
    turn = await store.turns.begin(THREAD)
    assert turn is not None
    assert (turn.status, turn.reason, turn.resume_count) == (TurnStatus.RUNNING, None, 0)
    assert turn.started_at is not None and turn.finished_at is None
    done = await store.turns.move(turn.id, TurnStatus.COMPLETED)
    assert done.status is TurnStatus.COMPLETED and done.finished_at is not None
    assert await store.turns.latest(THREAD) == done


async def test_a_second_open_turn_on_the_thread_is_refused(store: ThreadStore) -> None:
    first = await store.turns.begin(THREAD)
    assert first is not None
    assert await store.turns.begin(THREAD) is None
    assert await store.turns.latest(THREAD) == first
    assert await store.turns.begin("other") is not None  # other threads are independent


async def test_completed_cannot_run_again_and_is_left_unchanged(store: ThreadStore) -> None:
    turn = await store.turns.begin(THREAD)
    assert turn is not None
    done = await store.turns.move(turn.id, TurnStatus.COMPLETED)
    with pytest.raises(TurnTransitionError):
        await store.turns.move(turn.id, TurnStatus.RUNNING)
    assert await store.turns.resume(turn.id, 3) is None
    assert await store.turns.latest(THREAD) == done


async def test_an_unknown_turn_cannot_move(store: ThreadStore) -> None:
    with pytest.raises(TurnTransitionError):
        await store.turns.move("no-such-turn", TurnStatus.COMPLETED)


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
    turn = await store.turns.begin(THREAD)
    assert turn is not None
    with pytest.raises(ValueError, match="reason"):
        await store.turns.move(turn.id, target, reason)
    assert await store.turns.latest(THREAD) == turn


async def test_resume_counts_each_time_up_to_the_cap(store: ThreadStore) -> None:
    turn_id = await _interrupted(store)
    for expected in (1, 2):
        resumed = await store.turns.resume(turn_id, 2)
        assert resumed is not None
        assert (resumed.status, resumed.reason, resumed.resume_count) == (
            TurnStatus.RUNNING,
            None,
            expected,
        )
        await store.turns.move(turn_id, TurnStatus.INTERRUPTED, "rate_limited")
    assert await store.turns.resume(turn_id, 2) is None
    stays = await store.turns.latest(THREAD)
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
    other = await store.turns.begin(THREAD)
    assert other is not None
    assert await store.turns.resume(turn_id, 3) is None
    assert await store.turns.latest(THREAD) == other


async def test_an_interrupted_turn_can_be_abandoned_or_found_finished(store: ThreadStore) -> None:
    turn_id = await _interrupted(store)
    failed = await store.turns.move(turn_id, TurnStatus.FAILED, "superseded")
    assert (failed.status, failed.reason) == (TurnStatus.FAILED, "superseded")
    assert failed.finished_at is not None
    second = await _interrupted(store)
    done = await store.turns.move(second, TurnStatus.COMPLETED)
    assert (done.status, done.reason) == (TurnStatus.COMPLETED, None)


async def test_abandon_interrupts_only_an_open_turn_and_is_safe_to_repeat(
    store: ThreadStore,
) -> None:
    turn = await store.turns.begin(THREAD)
    assert turn is not None
    assert await store.turns.abandon(turn.id, "worker_lost")
    assert not await store.turns.abandon(turn.id, "worker_lost")
    assert not await store.turns.abandon("no-such-turn", "worker_lost")
    latest = await store.turns.latest(THREAD)
    assert latest is not None
    assert (latest.status, latest.reason) == (TurnStatus.INTERRUPTED, "worker_lost")


async def test_interrupt_open_frees_every_thread_or_just_one(store: ThreadStore) -> None:
    assert await store.turns.begin(THREAD) is not None
    assert await store.turns.begin("other") is not None
    assert await store.turns.interrupt_open("worker_lost", "other") == ["other"]
    assert await store.turns.interrupt_open("worker_lost") == [THREAD]
    assert await store.turns.interrupt_open("worker_lost") == []
    for thread in (THREAD, "other"):
        latest = await store.turns.latest(thread)
        assert latest is not None and latest.status is TurnStatus.INTERRUPTED
        assert await store.turns.begin(thread) is not None


async def test_usage_is_kept_per_turn(store: ThreadStore) -> None:
    turn = await store.turns.begin(THREAD)
    assert turn is not None
    await store.add_usage(THREAD, [CallUsage("m", 1, 0, 1)], turn.id)
    await store.add_usage(THREAD, [CallUsage("m", 2, 0, 2)])
    await store.add_usage(THREAD, [CallUsage("m", 3, 0, 3)], turn.id)
    expected = [CallUsage("m", 1, 0, 1), CallUsage("m", 3, 0, 3)]
    assert await store.turn_calls(THREAD, turn.id) == expected
    assert len(await store.session_calls(THREAD)) == 3


async def test_reset_deletes_the_threads_turns(store: ThreadStore) -> None:
    await _interrupted(store)
    assert await store.reset(THREAD)
    assert await store.turns.latest(THREAD) is None
