"""Tests for the thread snapshot: text messages, workspace and usage of a held thread."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.completion import NUDGE_NAME
from api.schemas.chat import RunningTurn
from api.services.snapshots import SnapshotOptions, last_answer, thread_messages, thread_snapshot
from storage.turn_model import PlannedInput, TurnStatus
from tests.api.keys import OTHER_OWNER, owned
from tests.fakes import InMemoryThreadStore

pytestmark = pytest.mark.anyio


async def test_only_user_and_assistant_text_is_kept() -> None:
    shown = thread_messages(
        [
            SystemMessage(content="rules"),
            HumanMessage(content="map hexane"),
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
            ToolMessage(content="{}", tool_call_id="1"),
            AIMessage(content="Here it is."),
        ],
    )
    assert [(m.role, m.text) for m in shown] == [
        ("user", "map hexane"),
        ("assistant", "Here it is."),
    ]


async def test_assistant_text_around_tool_calls_is_one_message() -> None:
    shown = thread_messages(
        [HumanMessage(content="q"), AIMessage(content="Looking."), AIMessage(content="Done.")],
    )
    assert [m.text for m in shown] == ["q", "Looking.\n\nDone."]


async def test_text_blocks_are_read_and_other_blocks_dropped() -> None:
    blocks: list[str | dict[str, object]] = [
        {"type": "text", "text": "Hi"},
        {"type": "tool_use", "id": "1"},
    ]
    assert thread_messages([AIMessage(content=blocks)])[0].text == "Hi"


async def test_unknown_thread_has_no_snapshot() -> None:
    assert (
        await thread_snapshot(InMemoryThreadStore(), owned("nope"), SnapshotOptions({}, 3)) is None
    )


async def test_held_thread_without_turns_has_an_empty_snapshot() -> None:
    threads = InMemoryThreadStore()
    await threads.claim(owned("a"))
    snapshot = await thread_snapshot(threads, owned("a"), SnapshotOptions({}, 3))
    assert snapshot is not None
    assert snapshot.messages == []
    assert snapshot.workspace.facilities == []
    assert snapshot.usage.calls == 0


async def test_a_completion_nudge_is_not_shown_and_the_text_after_it_joins_the_reply() -> None:
    shown = thread_messages(
        [
            HumanMessage(content="map hexane"),
            AIMessage(content="I will now gather the data."),
            HumanMessage(content="Continue now.", name=NUDGE_NAME),
            AIMessage(content="Here it is."),
        ],
    )
    assert [(m.role, m.text) for m in shown] == [
        ("user", "map hexane"),
        ("assistant", "I will now gather the data.\n\nHere it is."),
    ]


async def test_last_answer_is_the_last_assistant_text() -> None:
    messages = [
        HumanMessage(content="q1"),
        AIMessage(content="First."),
        HumanMessage(content="q2"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        ToolMessage(content="{}", tool_call_id="1"),
        AIMessage(content="Second."),
    ]
    assert last_answer(messages) == "Second."


async def test_no_answer_without_an_assistant_message() -> None:
    assert last_answer([HumanMessage(content="q")]) is None
    assert last_answer([]) is None


async def test_another_users_thread_has_no_snapshot() -> None:
    threads = InMemoryThreadStore()
    await threads.claim(owned("a"))
    assert await thread_snapshot(threads, owned("a", OTHER_OWNER), SnapshotOptions({}, 3)) is None


async def _history(threads: InMemoryThreadStore, messages: list[AnyMessage]) -> None:
    config: RunnableConfig = {"configurable": {"thread_id": owned("a").checkpoint_id}}
    graph = StateGraph(MessagesState)
    graph.add_node("noop", lambda state: {})
    graph.add_edge(START, "noop")
    graph.add_edge("noop", END)
    state: MessagesState = {"messages": messages}
    await graph.compile(checkpointer=threads.checkpointer).ainvoke(state, config)


async def test_a_running_turn_is_reported_and_its_part_of_the_history_left_to_its_events() -> None:
    threads = InMemoryThreadStore()
    await threads.claim(owned("a"))
    await _history(
        threads,
        [
            HumanMessage("first"),
            AIMessage("First answer."),
            HumanMessage("second"),
            AIMessage("Half"),
        ],
    )
    turn = await threads.turns.begin(owned("a"), PlannedInput("second", "second"))
    assert turn is not None
    snapshot = await thread_snapshot(threads, owned("a"), SnapshotOptions({}, 3))
    assert snapshot is not None
    assert [m.text for m in snapshot.messages] == ["first", "First answer."]
    assert snapshot.running_turn == RunningTurn(turn_id=turn.id, resumed=False, question="second")


async def test_a_queued_turn_whose_question_is_not_in_the_history_cuts_nothing() -> None:
    threads = InMemoryThreadStore()
    await threads.claim(owned("a"))
    await _history(threads, [HumanMessage("first"), AIMessage("First answer.")])
    await threads.turns.begin(owned("a"), PlannedInput("second", "second"))
    snapshot = await thread_snapshot(threads, owned("a"), SnapshotOptions({}, 3))
    assert snapshot is not None
    assert [m.text for m in snapshot.messages] == ["first", "First answer."]
    assert snapshot.running_turn is not None and snapshot.running_turn.question == "second"


async def test_a_finished_turn_shows_the_whole_history_and_no_running_turn() -> None:
    threads = InMemoryThreadStore()
    await threads.claim(owned("a"))
    await _history(threads, [HumanMessage("first"), AIMessage("Done.")])
    turn = await threads.turns.begin(owned("a"), PlannedInput("first", "first"))
    assert turn is not None
    await threads.turns.start(turn.owner_id, turn.id)
    await threads.turns.move(turn.owner_id, turn.id, TurnStatus.COMPLETED)
    snapshot = await thread_snapshot(threads, owned("a"), SnapshotOptions({}, 3))
    assert snapshot is not None
    assert [m.text for m in snapshot.messages] == ["first", "Done."]
    assert snapshot.running_turn is None
