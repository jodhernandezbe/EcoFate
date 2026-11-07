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
