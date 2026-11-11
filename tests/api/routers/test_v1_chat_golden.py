"""Golden event sequences of ``/api/v1/chat/stream``: the wire contract a refactor must keep.

Each scenario runs a scripted fake model through the endpoint and compares, in order, every
event's type, its payload keys and its stable values. Random or per-run values (sequence
numbers are checked separately; turn, request and correlation ids) are left out.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import StructuredTool
from pydantic import SecretStr

from agent.guardrails import ScopeGuard
from agent.missing import ask_text
from api.dependencies import AgentRuntime, get_runtime
from tests.api.conftest import ORIGIN, signed_in
from tests.api.services.projectors.factories import RULES, record
from tests.api.streams import parse_sse
from tests.fakes import KeyBench, ScriptedChatModel, reply, verdict
from tools.schemas import ConfirmationRequest, MissingEntry

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "g0L1d2E3n4" * 3  # pragma: allowlist secret
VOLATILE = frozenset({"seq", "turn_id", "correlation_id", "request_id", "state", "turn", "session"})
MISSING: MissingEntry = {
    "entry_id": "iur:1-1-1",
    "quantity": "iur",
    "subject": "1-1-1",
    "accepted_units": ["1/(ug/m^3)"],
    "minimum": 1e-9,
    "maximum": 1000.0,
    "purpose": "the cancer risk",
}


def _inventory(cas_number: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    shown: dict[str, object] = {"total_found": 1, "matching": 1, "shown": 1}
    return {**shown, "facilities": [record("A")], "note": "all"}, [record("A")]


def _toxicity(cas_number: str) -> str:
    return json.dumps({"cas_number": cas_number, "missing": [MISSING]})


INVENTORY = StructuredTool.from_function(
    _inventory,
    name="query_emissions_inventory",
    description="Synthetic inventory.",
    response_format="content_and_artifact",
)
TOXICITY = StructuredTool.from_function(_toxicity, name="get_toxicity", description="Synthetic.")
GUARD = ScopeGuard(classifier_prompt="CLASSIFY", fallback_reply="FALLBACK", history_window=4)


class _OutOfCredits(Exception):
    status_code = 429
    body = {"error": {"code": "insufficient_quota", "message": "raw provider text"}}


def _call(name: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name=name, args={"cas_number": "1-1-1"}, id="c0")],
    )


def _shape(event: dict[str, Any]) -> dict[str, Any]:
    """The event without its volatile values; their keys stay, so the shape is still compared."""
    stable = {k: v for k, v in event.items() if k not in VOLATILE}
    return {"keys": sorted(event), **stable}


@pytest.fixture
def stream(
    app: FastAPI,
    store: KeyBench,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Any]:
    store.give(KEY)
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [INVENTORY, TOXICITY])

    def run(runtime: AgentRuntime) -> list[dict[str, Any]]:
        app.dependency_overrides[get_runtime] = lambda: runtime
        with signed_in(app, raise_server_exceptions=False) as client:
            body = {"thread_id": "g1", "message": "Assess 1-1-1"}
            response = client.post("/api/v1/chat/stream", json=body, headers=OWN)
        events = parse_sse(response.text)
        assert [e["seq"] for e in events] == list(range(len(events)))
        assert KEY not in response.text
        return [_shape(e) for e in events]

    yield run


def _runtime(model: BaseChatModel, **extra: Any) -> AgentRuntime:
    labels = {"query_emissions_inventory": "Found facilities", "get_toxicity": "Read toxicity"}
    return AgentRuntime(
        lambda key: model,
        10,
        labels,
        model_name="m",
        workspace_rules=RULES,
        **extra,
    )


START = {
    "keys": ["resumed", "seq", "thread_id", "turn_id", "type"],
    "type": "turn_started",
    "thread_id": "g1",
    "resumed": False,
}
USAGE = {"keys": ["seq", "session", "turn", "type"], "type": "usage"}
FINISHED = {"keys": ["seq", "type"], "type": "turn_finished"}
STATUS_KEYS = ["call_id", "label", "phase", "seq", "status", "tool_name", "type"]
WORKSPACE = {"keys": ["seq", "state", "type"], "type": "workspace_update"}


def _status(phase: str, name: str, label: str, status: str | None) -> dict[str, Any]:
    base = {"type": "tool_status", "phase": phase, "call_id": "c0", "tool_name": name}
    return {"keys": STATUS_KEYS, **base, "label": label, "status": status}


def _token(text: str) -> dict[str, Any]:
    return {"keys": ["seq", "text", "type"], "type": "token", "text": text}


def _message(text: str) -> dict[str, Any]:
    return {"keys": ["seq", "text", "type"], "type": "assistant_message", "text": text}


def test_tool_call_then_answer(stream: Any) -> None:
    model = ScriptedChatModel([_call("query_emissions_inventory"), reply("Done now", 10, 2)])
    assert stream(_runtime(model)) == [
        START,
        _status("started", "query_emissions_inventory", "Found facilities", None),
        _status("finished", "query_emissions_inventory", "Found facilities", "ok"),
        WORKSPACE,
        _token("Done"),
        _token(" "),
        _token("now"),
        _message("Done now"),
        USAGE,
        FINISHED,
    ]


def test_missing_value_asks_for_confirmation(stream: Any) -> None:
    model = ScriptedChatModel([_call("get_toxicity"), reply("never reached", 10, 2)])
    question = ask_text(ConfirmationRequest(request_id="x", entries=[MISSING]))
    request_keys = ["entries", "request_id", "seq", "type"]
    assert stream(_runtime(model)) == [
        START,
        _status("started", "get_toxicity", "Read toxicity", None),
        _status("finished", "get_toxicity", "Read toxicity", "ok"),
        WORKSPACE,
        _message(question),
        {"keys": request_keys, "type": "confirmation_request", "entries": [MISSING]},
        USAGE,
        FINISHED,
    ]


def test_off_topic_turn_is_redirected(stream: Any) -> None:
    model = ScriptedChatModel([], classifier=[verdict(False, "Back to chemicals.", (5, 1))])
    assert stream(_runtime(model, scope_guard=GUARD)) == [
        START,
        {"keys": ["in_scope", "seq", "type"], "type": "scope", "in_scope": False},
        {"keys": ["seq", "text", "type"], "type": "guardrail_pivot", "text": "Back to chemicals."},
        USAGE,
        FINISHED,
    ]


def test_provider_failure_interrupts_with_a_fixed_message(stream: Any) -> None:
    def build(key: SecretStr) -> BaseChatModel:
        raise _OutOfCredits("raw provider text")

    runtime = AgentRuntime(build, 10, model_name="m")
    events = stream(runtime)
    assert [e["type"] for e in events] == [
        "turn_started",
        "turn_interrupted",
        "usage",
        "turn_finished",
    ]
    interrupted = events[1]
    assert interrupted["keys"] == ["message", "reason", "resumable", "seq", "type"]
    assert (interrupted["reason"], interrupted["resumable"]) == ("out_of_credits", True)
    assert "no credits" in interrupted["message"]
    assert "raw provider text" not in interrupted["message"]
