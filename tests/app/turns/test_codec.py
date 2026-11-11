"""Every event a worker relays survives the trip as a record; a record that does not fit is
absent."""

from __future__ import annotations

import json
from typing import cast

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.turns.codec import (
    RelayedEvent,
    TurnQueued,
    TurnStopped,
    WorkerStarted,
    decode,
    encode,
    is_last,
)
from app.turns.events import (
    AgentStarted,
    AssistantText,
    ConfirmationNeeded,
    ScopePassed,
    ScopeRedirect,
    TextDelta,
    ToolCalls,
    ToolFinished,
    ToolResults,
    ToolStarted,
    TurnBegan,
    TurnDone,
    TurnFailed,
    TurnUsage,
)
from app.turns.failures import FailureReason
from app.usage_meter import CallUsage
from tools.schemas import ConfirmationRequest

CALL = AIMessage("", tool_calls=[{"id": "c1", "name": "lookup", "args": {"q": "x"}}])
RESULT = ToolMessage('{"ok": true}', tool_call_id="c1", name="lookup")
REQUEST = cast(ConfirmationRequest, {"request_id": "r1", "entries": [{"entry_id": "e"}]})
EVENTS: list[RelayedEvent] = [
    TurnQueued(2),
    WorkerStarted(),
    TurnBegan(),
    AgentStarted(),
    TextDelta("he"),
    AssistantText("hello"),
    ToolStarted("c1", "lookup"),
    ToolCalls(CALL),
    ToolFinished("c1", "lookup", False, RESULT),
    ToolResults((RESULT,)),
    ScopePassed(),
    ScopeRedirect(("go back", "really")),
    ConfirmationNeeded(REQUEST),
    TurnStopped(FailureReason.CANCELLED, "abc123", True),
    TurnUsage((CallUsage("m", 10, 2, 5),), (CallUsage("m", None, 0, None),)),
    TurnDone(),
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: type(e).__name__)
def test_each_event_round_trips_through_json(event: RelayedEvent) -> None:
    record = json.loads(json.dumps(encode(event)))
    assert decode(record) == event


def test_only_the_end_is_last() -> None:
    assert [is_last(e) for e in EVENTS].count(True) == 1
    assert is_last(TurnDone())


def test_a_failure_never_travels() -> None:
    with pytest.raises(TypeError):
        encode(TurnFailed(FailureReason.UNEXPECTED, "x"))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "record",
    [
        "text",
        {"text": "no kind"},
        {"kind": "unknown"},
        {"kind": 3},
        {"kind": "text", "text": 5},
        {"kind": "stopped", "reason": "invented", "correlation_id": "x", "resumable": True},
        {"kind": "stopped", "reason": "cancelled", "correlation_id": "x", "resumable": 1},
        {"kind": "usage", "turn": [{"model": "m", "input_tokens": True}], "session": []},
        {"kind": "usage", "turn": [{"model": "m", "input_tokens": -1}], "session": []},
        {"kind": "tool_calls", "message": {"type": "tool", "data": {}}},
        {"kind": "tool_results", "messages": ["not a message"]},
        {"kind": "scope_redirect", "texts": ["ok", 3]},
        {"kind": "confirmation", "request": {"entries": []}},
        {"kind": "queued", "position": -1},
    ],
)
def test_a_record_that_does_not_fit_is_absent(record: object) -> None:
    assert decode(record) is None
