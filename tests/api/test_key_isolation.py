"""Key isolation end to end: one user's key is never another's, no endpoint returns a key, and
no key, token or password reaches a log line, a span or the process environment."""

from __future__ import annotations

import inspect
import io
import logging
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID

import logfire
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic import SecretStr

import app.redaction as redaction
from api.dependencies import AgentRuntime, get_runtime
from api.schemas.chat import ChatRequest, ErrorEvent
from api.services.provider_errors import NO_KEY_MESSAGE
from app.operator_keys import OperatorKeys
from app.redaction import SecretRedactionFilter, protect_for_process
from app.telemetry import scrubbing_options
from config.telemetry import TelemetrySettings
from config.ui import UiSettings
from storage.user_credentials import CredentialRepository
from tests.api.auth_support import build_app
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import OTHER_OWNER, OWNER
from tests.api.services.test_agent_runner import _keys  # pyright: ignore[reportPrivateUsage]
from tests.api.streams import begun_turn, parse_sse
from tests.fakes import InMemoryThreadStore, KeyBench, ScriptedChatModel, scripted

OWN = {"Origin": ORIGIN}
CHAT = "/api/v1/chat/stream"
KEY_A = "sk-proj-" + "A1b2C3d4E5" * 3  # pragma: allowlist secret
KEY_B = "sk-proj-" + "B6f7G8h9I0" * 3  # pragma: allowlist secret
CENSUS = "census-operator-" + "c7" * 12  # pragma: allowlist secret
COMPTOX = "comptox-operator-" + "t9" * 12  # pragma: allowlist secret
KEK = "kek-" + "Q9w2E8r7T6y5U4i3O2p1A0s9D8f7G6h5"  # pragma: allowlist secret
SESSION_SECRET = "session-secret-" + "s5" * 16  # pragma: allowlist secret
SMTP_PASSWORD = "smtp-password-" + "p3" * 12  # pragma: allowlist secret
DB_PASSWORD = "Tr0ub4dor3x"  # pragma: allowlist secret
DATABASE_URL = f"postgresql://ecofate:{DB_PASSWORD}@db:5432/ecofate"
OPERATOR = OperatorKeys(census=SecretStr(CENSUS), comptox=SecretStr(COMPTOX))
PROCESS_SECRETS = (CENSUS, COMPTOX, KEK, SESSION_SECRET, SMTP_PASSWORD)
EVERYTHING = (KEY_A, KEY_B, *PROCESS_SECRETS, DB_PASSWORD)


@pytest.fixture(autouse=True)
def _isolated_process_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    empty: set[str] = set()
    monkeypatch.setattr(redaction, "_PROCESS_LITERALS", empty)


# --- 5.1 isolation ----------------------------------------------------------------------------


def _signed_in_pair(app: FastAPI) -> tuple[TestClient, TestClient]:
    return (
        signed_in(app, email="a@example.com", raise_server_exceptions=False),
        signed_in(app, email="b@example.com", raise_server_exceptions=False),
    )


@pytest.fixture
def store() -> KeyBench:
    """The key services the ``app`` fixture is built with (the installation has operator keys)."""
    return KeyBench(OPERATOR)


@pytest.fixture
def bench(store: KeyBench) -> KeyBench:
    return store


@pytest.fixture
def seen_keys(app: FastAPI) -> list[str]:
    """Every key a chat model was built with, in order."""
    seen: list[str] = []

    def build(key: SecretStr) -> BaseChatModel:
        seen.append(key.get_secret_value())
        return scripted("an answer", "an answer", "an answer")

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(build, 10)
    return seen


@pytest.fixture
def two_users(app: FastAPI) -> Iterator[tuple[TestClient, TestClient]]:
    ana, bo = _signed_in_pair(app)
    with ana, bo:
        yield ana, bo


def test_only_a_has_a_key_so_b_status_is_false_and_b_cannot_chat(
    bench: KeyBench,
    two_users: tuple[TestClient, TestClient],
    seen_keys: list[str],
) -> None:
    ana, bo = two_users
    bench.give(KEY_A, OWNER)
    assert ana.get("/api/v1/settings/openai-key").json() == {"configured": True}
    assert bo.get("/api/v1/settings/openai-key").json() == {"configured": False}
    events = parse_sse(bo.post(CHAT, json={"thread_id": "t", "message": "hi"}, headers=OWN).text)
    assert [e["message"] for e in events if e["type"] == "error"] == [NO_KEY_MESSAGE]
    assert seen_keys == []  # A's key was never used for B


def test_a_ciphertext_copied_into_b_row_fails_and_b_ends_with_the_missing_key_message(
    bench: KeyBench,
    two_users: tuple[TestClient, TestClient],
    seen_keys: list[str],
) -> None:
    ana, bo = two_users
    bench.give(KEY_A, OWNER)
    stolen = bench.rows.rows[(OWNER, "openai")]
    bench.rows.rows[(OTHER_OWNER, "openai")] = replace(stolen, user_id=OTHER_OWNER)
    events = parse_sse(bo.post(CHAT, json={"thread_id": "t", "message": "hi"}, headers=OWN).text)
    assert [e["message"] for e in events if e["type"] == "error"] == [NO_KEY_MESSAGE]
    assert seen_keys == []
    ok = parse_sse(ana.post(CHAT, json={"thread_id": "t", "message": "hi"}, headers=OWN).text)
    assert [e for e in ok if e["type"] == "error"] == []
    assert set(seen_keys) == {KEY_A}


def test_each_user_chats_under_their_own_key(
    bench: KeyBench,
    two_users: tuple[TestClient, TestClient],
    seen_keys: list[str],
) -> None:
    ana, bo = two_users
    bench.give(KEY_A, OWNER)
    bench.give(KEY_B, OTHER_OWNER)
    ana.post(CHAT, json={"thread_id": "t", "message": "hi"}, headers=OWN)
    assert set(seen_keys) == {KEY_A}
    bo.post(CHAT, json={"thread_id": "t", "message": "hi"}, headers=OWN)
    assert set(seen_keys) == {KEY_A, KEY_B}


def test_every_repository_method_acting_on_one_user_requires_the_user_id() -> None:
    methods = {
        name: inspect.signature(member)
        for name, member in inspect.getmembers(CredentialRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    across_users = {"unsealed_by_other_keys", "count_sealed_by"}  # rotation only
    for name, signature in methods.items():
        if name in across_users:
            continue
        assert "user_id" in signature.parameters or "credential" in signature.parameters, name


# --- 5.2 concurrent turns ---------------------------------------------------------------------


@tool
def probe_key() -> str:
    """Report the provider key this tool can see."""
    from tools.credentials import PROVIDER_KEY

    key = PROVIDER_KEY.get()
    return key.get_secret_value() if key is not None else "none"


@pytest.mark.anyio
async def test_concurrent_turns_of_two_users_see_only_their_own_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_key])
    bench, threads = KeyBench(), InMemoryThreadStore()
    bench.give(KEY_A, OWNER)
    bench.give(KEY_B, OTHER_OWNER)
    models: dict[str, str] = {}
    tools: dict[str, str] = {}

    async def turn(thread: str, owner_id: UUID) -> None:

        def build(key: SecretStr) -> BaseChatModel:
            models[thread] = key.get_secret_value()
            call = AIMessage(content="", tool_calls=[{"name": "probe_key", "args": {}, "id": "c"}])
            return ScriptedChatModel([call, AIMessage(content="done")])

        events = begun_turn(
            ChatRequest(thread_id=thread, message="go"),
            owner_id=owner_id,
            keys=_keys(bench, owner_id),
            threads=threads,
            runtime=AgentRuntime(build, 10),
        )
        [event async for event in events]
        saved = threads.checkpointer.get_tuple(
            {"configurable": {"thread_id": f"{owner_id}:{thread}"}},
        )
        assert saved is not None
        messages = saved.checkpoint["channel_values"]["messages"]
        tools[thread] = next(m.content for m in messages if m.type == "tool")

    await asyncio.gather(turn("a", OWNER), turn("b", OTHER_OWNER))
    assert models == {"a": KEY_A, "b": KEY_B}
    assert tools == {"a": KEY_A, "b": KEY_B}


# --- 5.3 no leak ------------------------------------------------------------------------------


def _get_paths(app: FastAPI) -> list[str]:
    paths = cast(dict[str, dict[str, object]], app.openapi()["paths"])
    return [path for path, ops in paths.items() if "get" in ops and "{" not in path]


def test_no_get_endpoint_returns_any_key_character_sequence(
    app: FastAPI,
    bench: KeyBench,
    client: TestClient,
) -> None:
    bench.give(KEY_A, OWNER)
    paths = _get_paths(app)
    assert "/api/v1/settings/keys" in paths
    for path in paths:
        body = client.get(path).text
        for secret in (KEY_A, CENSUS, COMPTOX):
            assert secret not in body, path
        assert KEY_A[-6:] not in body, path  # not even a suffix


def test_the_status_is_only_a_boolean(app: FastAPI, bench: KeyBench, client: TestClient) -> None:
    bench.give(KEY_A, OWNER)
    assert client.get("/api/v1/settings/openai-key").json() == {"configured": True}


def test_the_removed_operator_routes_answer_404_with_the_frontend_served(
    settings: UiSettings,
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<html>shell</html>")
    bench = KeyBench(OPERATOR)
    app = build_app(replace(settings, frontend_dist=tmp_path), keys=bench.services)
    with signed_in(app, raise_server_exceptions=False) as client:
        for name in ("census-key", "comptox-key"):
            path = f"/api/v1/settings/{name}"
            assert client.post(path, json={"api_key": KEY_A}, headers=OWN).status_code == 404
            assert client.delete(path, headers=OWN).status_code == 404
    assert bench.rows.rows == {}


def test_a_provider_failure_carries_no_key_in_the_response(
    app: FastAPI,
    bench: KeyBench,
    client: TestClient,
) -> None:
    bench.give(KEY_A, OWNER)

    def build(key: SecretStr) -> BaseChatModel:
        raise RuntimeError(f"provider rejected {key.get_secret_value()} and {CENSUS}")

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(build, 10)
    response = client.post(CHAT, json={"thread_id": "t", "message": "hi"}, headers=OWN)
    errors = [e for e in parse_sse(response.text) if e["type"] == "error"]
    assert len(errors) == 1
    assert set(errors[0]) >= {"message", "correlation_id"}
    assert KEY_A not in response.text and CENSUS not in response.text
    assert ErrorEvent  # the wire type the event follows


# --- 5.4 logs and spans -----------------------------------------------------------------------


@tool
def leaky() -> str:
    """A tool whose result and log line carry every secret (the worst case)."""
    text = " ".join([KEY_A, *PROCESS_SECRETS, DATABASE_URL])
    logging.getLogger("tools.leaky").warning("leaky tool saw %s", text)
    return text


def _leaky_model() -> BaseChatModel:
    call = AIMessage(content="", tool_calls=[{"name": "leaky", "args": {}, "id": "c1"}])
    return ScriptedChatModel([call, AIMessage(content=f"done {' '.join(EVERYTHING)}")])


@pytest.mark.anyio
async def test_no_secret_reaches_a_log_line_or_a_span(
    monkeypatch: pytest.MonkeyPatch,
    monitoring: TelemetrySettings,
) -> None:
    protect_for_process(PROCESS_SECRETS)
    memory = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        scrubbing=scrubbing_options(monitoring, PROCESS_SECRETS),
        additional_span_processors=[SimpleSpanProcessor(memory)],
    )
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [leaky])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    bench = KeyBench(OPERATOR)
    bench.give(KEY_A, OWNER)
    runtime = AgentRuntime(lambda key: _leaky_model(), 10, telemetry=monitoring)
    try:
        events = begun_turn(
            ChatRequest(thread_id="t", message=f"hello {KEY_A} {DATABASE_URL}"),
            keys=_keys(bench),
            threads=InMemoryThreadStore(),
            runtime=runtime,
        )
        [event async for event in events]
        logfire.force_flush()
    finally:
        root.removeHandler(handler)
    logs = stream.getvalue()
    spans = " ".join(str(dict(s.attributes or {})) for s in memory.exported_spans)
    assert "leaky tool saw" in logs  # the log line was emitted, and redacted
    assert memory.exported_spans
    for secret in EVERYTHING:
        assert secret not in logs, secret
        assert secret not in spans, secret


# --- 5.7 the process environment --------------------------------------------------------------


@pytest.mark.anyio
async def test_the_environment_never_holds_the_users_key_after_a_turn() -> None:
    bench = KeyBench(OPERATOR)
    bench.give(KEY_A, OWNER)
    events = begun_turn(
        ChatRequest(thread_id="t", message="go"),
        keys=_keys(bench),
        threads=InMemoryThreadStore(),
        runtime=AgentRuntime(lambda key: scripted("ok"), 10),
    )
    [event async for event in events]
    assert all(KEY_A not in value for value in os.environ.values())
    assert all(CENSUS not in value for value in os.environ.values())
