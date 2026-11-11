"""Tests for the chat routes: SSE framing, one turn per thread, reset, origin rule."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from api.dependencies import AgentRuntime, get_runtime
from api.services.threads import ThreadStore
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import owned
from tests.api.streams import parse_sse
from tests.fakes import (
    KeyBench,
    ScriptedChatModel,
    scripted,
)

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "r4T5y6U7i8" * 3  # pragma: allowlist secret


@pytest.fixture
def keyed(store: KeyBench) -> KeyBench:
    store.give(KEY)
    return store


@pytest.fixture
def chat(app: FastAPI, keyed: KeyBench) -> Iterator[TestClient]:
    model = scripted("an answer", "another answer")
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with signed_in(app, raise_server_exceptions=False) as client:
        yield client


def _post(client: TestClient, thread: str = "t1") -> Response:
    return client.post(
        "/api/v1/chat/stream",
        json={"thread_id": thread, "message": "hello"},
        headers=OWN,
    )


def test_stream_is_sse_with_ordered_events(chat: TestClient) -> None:
    response = _post(chat)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [e["type"] for e in events][0] == "turn_started"
    assert events[-1]["type"] == "turn_finished"
    assert [e["seq"] for e in events] == sorted({e["seq"] for e in events})  # strictly increasing
    assert KEY not in response.text


def test_busy_thread_is_409_and_others_are_unaffected(chat: TestClient, app: FastAPI) -> None:
    threads: ThreadStore = app.state.threads
    asyncio.run(threads.claim(owned("t1")))
    assert _post(chat, "t1").status_code == 409
    assert _post(chat, "t2").status_code == 200
    asyncio.run(threads.release(owned("t1")))
    assert _post(chat, "t1").status_code == 200


def test_thread_is_released_after_the_turn(chat: TestClient) -> None:
    assert _post(chat).status_code == 200
    assert _post(chat).status_code == 200


def test_reset_clears_history_and_refuses_while_busy(chat: TestClient, app: FastAPI) -> None:
    _post(chat)
    assert chat.delete("/api/v1/chat/threads/t1", headers=OWN).status_code == 204
    asyncio.run(app.state.threads.claim(owned("t1")))
    assert chat.delete("/api/v1/chat/threads/t1", headers=OWN).status_code == 409


def test_chat_requires_the_own_origin(chat: TestClient) -> None:
    response = chat.post("/api/v1/chat/stream", json={"thread_id": "t1", "message": "hi"})
    assert response.status_code == 403


@pytest.mark.parametrize("body", [{"thread_id": "t1"}, {"thread_id": "a b", "message": "x"}])
def test_invalid_bodies_are_422(chat: TestClient, body: dict[str, str]) -> None:
    assert chat.post("/api/v1/chat/stream", json=body, headers=OWN).status_code == 422


def test_no_key_streams_an_error_event(app: FastAPI) -> None:
    model = scripted("never used")
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with signed_in(app) as client:
        events = parse_sse(_post(client).text)
    assert [e["type"] for e in events] == [
        "turn_started",
        "turn_status",  # queued
        "turn_status",  # running
        "error",
        "usage",
        "turn_finished",
    ]


def test_stream_carries_the_configured_step_labels(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool

    @tool
    def lookup() -> str:
        """A stand-in tool."""
        return "result"

    call = AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "c1"}])
    model = ScriptedChatModel([call, AIMessage(content="done")])
    runtime = AgentRuntime(lambda key: model, 10, {"lookup": "Looked something up"})
    app.dependency_overrides[get_runtime] = lambda: runtime
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("agent.graph.get_all_tools", lambda: [lookup])
        with signed_in(app) as client:
            events = parse_sse(_post(client).text)
    steps = [(e["phase"], e["label"]) for e in events if e["type"] == "tool_status"]
    assert steps == [("started", "Looked something up"), ("finished", "Looked something up")]


def test_shipped_runtime_labels_every_registered_tool() -> None:
    from tools.registry import get_all_tools

    labels = get_runtime().step_labels
    assert {tool.name for tool in get_all_tools()} <= set(labels)


def test_the_web_runtime_guards_scope_and_extends_the_standard_prompt() -> None:
    from prompts.registry import load_prompt

    runtime = get_runtime()
    standard = load_prompt("agent_system")
    addendum = load_prompt("scope_addendum")
    assert runtime.scope_guard is not None
    assert runtime.system_prompt == f"{standard}\n\n{addendum}"
    assert runtime.scope_guard.classifier_prompt == load_prompt("scope_classifier")
    assert runtime.scope_guard.fallback_reply == load_prompt("scope_redirect_fallback")


def test_the_command_line_agent_keeps_the_standard_prompt_and_no_guard() -> None:
    import inspect

    from app import run

    source = inspect.getsource(run)
    assert "scope_guard" not in source and "system_prompt" not in source


def test_snapshot_returns_the_turns_of_a_held_thread(chat: TestClient) -> None:
    _post(chat, "t9")
    body = chat.get("/api/v1/chat/threads/t9").json()
    assert body["thread_id"] == "t9"
    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("user", "hello"),
        ("assistant", "an answer"),
    ]
    assert body["workspace"]["facilities"] == []
    assert body["usage"]["calls"] >= 0
    assert KEY not in str(body)


def test_snapshot_of_an_unknown_thread_is_a_generic_404(chat: TestClient) -> None:
    response = chat.get("/api/v1/chat/threads/never-seen")
    assert response.status_code == 404
    assert set(response.json()) == {"error", "correlation_id"}


def test_snapshot_rejects_a_malformed_id(chat: TestClient) -> None:
    assert chat.get("/api/v1/chat/threads/bad.id").status_code == 422


def test_snapshot_does_not_change_the_thread(chat: TestClient) -> None:
    _post(chat, "t8")
    first = chat.get("/api/v1/chat/threads/t8").json()
    assert chat.get("/api/v1/chat/threads/t8").json() == first


def test_snapshot_survives_a_reset_as_a_404(chat: TestClient) -> None:
    _post(chat, "t7")
    chat.delete("/api/v1/chat/threads/t7", headers=OWN)
    assert chat.get("/api/v1/chat/threads/t7").status_code == 404
