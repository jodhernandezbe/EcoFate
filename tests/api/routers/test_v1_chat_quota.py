"""The daily turn quota over the chat routes and the quota endpoint (in-memory store)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from pydantic import PrivateAttr

from api.dependencies import AgentRuntime, get_runtime
from api.services.quota import QuotaService
from api.services.threads import ThreadStore
from api.services.turn_lifecycle import BUSY
from config.limits import LimitSettings, get_limit_settings
from tests.api.conftest import ORIGIN, make_user, signed_in
from tests.api.keys import OWNER, owned
from tests.api.streams import parse_sse
from tests.fakes import KeyBench, ScriptedChatModel, reply, scripted
from tests.fakes_quota import InMemoryQuota
from tools.schemas import ConfirmationRequest, MissingEntry

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "z9X8c7V6b5" * 3  # pragma: allowlist secret
LIMIT = 2
THREAD = "q1"
IUR = "iur:71-43-2"


@tool
def lookup(cas_number: str) -> str:
    """Look up a CAS number."""
    return f"found {cas_number}"


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup])


@pytest.fixture
def quota_store() -> InMemoryQuota:
    return InMemoryQuota()


@pytest.fixture
def configure(app: FastAPI, quota_store: InMemoryQuota) -> Callable[..., LimitSettings]:
    """Put a quota over ``quota_store`` on the app, with the shipped limits changed as asked."""

    def apply(**changes: Any) -> LimitSettings:  # noqa: ANN401
        settings = replace(get_limit_settings(), daily_turns_per_user=LIMIT, **changes)
        app.state.quota = QuotaService(quota_store, settings)
        return settings

    return apply


@pytest.fixture
def keyed(store: KeyBench) -> KeyBench:
    store.give(KEY)
    return store


def _use(app: FastAPI, model: ScriptedChatModel, built: list[int] | None = None) -> None:
    def build(key: object) -> ScriptedChatModel:
        if built is not None:
            built.append(1)
        return model

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(build, 10)


def _send(client: TestClient, thread: str = THREAD, message: str = "Assess 1-1-1") -> Response:
    body = {"thread_id": thread, "message": message}
    return client.post("/api/v1/chat/stream", json=body, headers=OWN)


def _usage(store: InMemoryQuota, user_id: Any = OWNER) -> int:  # noqa: ANN401
    return asyncio.run(store.usage(user_id))


def _calls(*ids: str) -> AIMessage:
    calls = [ToolCall(name="lookup", args={"cas_number": f"cas-{i}"}, id=i) for i in ids]
    return AIMessage(content="", tool_calls=calls)


@pytest.fixture
def chat(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
) -> Iterator[TestClient]:
    configure()
    _use(app, scripted(*["an answer"] * 10))
    with signed_in(app, raise_server_exceptions=False) as client:
        yield client


# --- counting --------------------------------------------------------------------------------


def test_turns_up_to_the_limit_run_and_the_next_is_refused(
    chat: TestClient,
    quota_store: InMemoryQuota,
) -> None:
    statuses = [_send(chat, f"t{i}").status_code for i in range(LIMIT + 1)]
    assert statuses == [200, 200, 429]
    assert _usage(quota_store) == LIMIT


def test_the_refusal_has_the_message_limit_reset_and_retry_after(
    chat: TestClient,
    configure: Callable[..., LimitSettings],
) -> None:
    settings = configure()
    for i in range(LIMIT):
        _send(chat, f"t{i}")
    response = _send(chat, "late")
    body = response.json()
    assert response.status_code == 429
    assert set(body) == {"detail", "limit", "resets_at", "correlation_id"}
    assert body["detail"] == settings.exhausted_message
    assert body["limit"] == LIMIT
    resets_at = datetime.fromisoformat(body["resets_at"])
    assert (resets_at.hour, resets_at.minute, resets_at.second) == (0, 0, 0)
    assert 1 <= int(response.headers["Retry-After"]) <= 24 * 3600
    assert body["correlation_id"]


def test_a_refused_turn_builds_no_model_and_leaves_the_thread_free(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
) -> None:
    configure()
    built: list[int] = []
    _use(app, scripted(*["an answer"] * 10), built)
    with signed_in(app, raise_server_exceptions=False) as client:
        for i in range(LIMIT):
            _send(client, f"t{i}")
        before = len(built)
        assert _send(client, "refused").status_code == 429
        assert len(built) == before
        threads: ThreadStore = app.state.threads
        assert asyncio.run(threads.claim(owned("refused")))  # not left busy
        assert asyncio.run(threads.turns.latest(owned("refused"))) is None


def test_a_busy_thread_is_409_and_not_counted(
    chat: TestClient,
    app: FastAPI,
    quota_store: InMemoryQuota,
) -> None:
    assert asyncio.run(app.state.threads.claim(owned(THREAD)))
    response = _send(chat)
    assert (response.status_code, response.json()["error"]) == (409, BUSY)
    assert quota_store.calls == []


def test_a_signed_out_request_is_401_and_not_counted(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure()
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        assert _send(client).status_code == 401
    assert quota_store.calls == []


def test_a_user_without_a_key_is_not_charged(
    app: FastAPI,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure()
    _use(app, scripted("never used"))
    with signed_in(app, raise_server_exceptions=False) as client:
        events = parse_sse(_send(client).text)
        assert events[-3]["type"] == "error"
        assert _usage(quota_store) == 0  # counted, then given back before the model
        assert len(quota_store.refunded) == 1
        assert _send(client, "again").status_code == 200  # not stuck at a count of 1


# --- free continuations ----------------------------------------------------------------------


def _open_request(threads: ThreadStore) -> None:
    entry = MissingEntry(
        entry_id=IUR,
        quantity="iur",
        subject="71-43-2",
        accepted_units=["1/(ug/m^3)", "1/(mg/m^3)"],
        minimum=1e-9,
        maximum=1000.0,
        purpose="the cancer risk",
    )
    asyncio.run(threads.touch(owned("c1")))
    request = ConfirmationRequest(request_id="req1", entries=[entry])
    asyncio.run(threads.set_pending(owned("c1"), request))


def _answer(request_id: str) -> dict[str, object]:
    entry = {"entry_id": IUR, "decision": "supply", "number": 0.002, "unit": "1/(mg/m^3)"}
    return {"thread_id": "c1", "answers": {"request_id": request_id, "entries": [entry]}}


def test_a_valid_confirmation_answer_at_the_limit_runs_and_is_free(
    chat: TestClient,
    app: FastAPI,
    quota_store: InMemoryQuota,
) -> None:
    for i in range(LIMIT):
        _send(chat, f"t{i}")
    _open_request(app.state.threads)
    response = chat.post("/api/v1/chat/stream", json=_answer("req1"), headers=OWN)
    assert response.status_code == 200
    assert _usage(quota_store) == LIMIT
    assert len(quota_store.calls) == LIMIT


def test_a_forged_confirmation_answer_is_rejected_and_not_free(
    chat: TestClient,
    app: FastAPI,
    quota_store: InMemoryQuota,
) -> None:
    for i in range(LIMIT):
        _send(chat, f"t{i}")
    response = chat.post("/api/v1/chat/stream", json=_answer("forged"), headers=OWN)
    assert response.status_code == 409  # no such open request: nothing runs
    assert asyncio.run(app.state.threads.turns.latest(owned("c1"))) is None
    assert len(quota_store.calls) == LIMIT
    assert _send(chat, "new").status_code == 429  # and a message is still refused


def test_a_message_while_a_request_is_open_is_a_new_counted_turn(
    chat: TestClient,
    app: FastAPI,
    quota_store: InMemoryQuota,
) -> None:
    _open_request(app.state.threads)
    assert _send(chat, "c1", "never mind").status_code == 200
    assert _usage(quota_store) == 1


def test_resuming_an_interrupted_turn_is_free_at_the_limit(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure()
    model = FlakyModel([_calls("c0"), _calls("c1"), reply("done", 2, 1)], fail_at=[1])
    _use(app, model)
    with signed_in(app, raise_server_exceptions=False) as client:
        types = [e["type"] for e in parse_sse(_send(client).text)]
        assert "turn_interrupted" in types
        assert _send(client, "other").status_code == 200  # the second counted turn
        assert _send(client, "third").status_code == 429
        resumed = client.post(f"/api/v1/chat/threads/{THREAD}/resume", headers=OWN)
        assert resumed.status_code == 200
    assert _usage(quota_store) == LIMIT
    assert len(quota_store.calls) == LIMIT + 1  # the refused third try is the only extra call


# --- refunds ---------------------------------------------------------------------------------


class ProviderOutOfCredits(Exception):
    """Stands in for the provider's 429 ``insufficient_quota`` (status and code only)."""

    status_code = 429
    body: dict[str, object] = {"error": {"code": "insufficient_quota"}}  # noqa: RUF012 - stand-in


class FlakyModel(ScriptedChatModel):
    """A scripted model that raises ``error`` on the given calls (0-based)."""

    _fail_at: list[int] = PrivateAttr(default_factory=list[int])
    _error: Exception = PrivateAttr(default_factory=lambda: ProviderOutOfCredits("raw text"))

    def __init__(
        self,
        script: Sequence[AIMessage],
        fail_at: list[int],
        error: Exception | None = None,
    ) -> None:
        super().__init__(script)
        self._fail_at = list(fail_at)
        if error is not None:
            self._error = error

    def _next(self, messages: Any = None) -> AIMessage:  # noqa: ANN401
        if self._cursor in self._fail_at:
            self._fail_at.remove(self._cursor)
            raise self._error
        return super()._next(messages)


class _Boom(ScriptedChatModel):
    """Answers the first call with a tool call and fails the second (no provider code)."""

    def __init__(self, script: Sequence[AIMessage]) -> None:
        super().__init__(script)

    def _next(self, messages: Any = None) -> AIMessage:  # noqa: ANN401
        if self._cursor >= 1:
            raise RuntimeError("boom")
        return super()._next(messages)


def test_a_failure_before_any_model_call_is_refunded_once(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure()
    _use(app, FlakyModel([reply("x", 1, 1)], fail_at=[0], error=RuntimeError("boom")))
    with signed_in(app, raise_server_exceptions=False) as client:
        assert [e["type"] for e in parse_sse(_send(client).text)][-3] == "error"
    assert _usage(quota_store) == 0
    assert len(quota_store.refunded) == 1


def test_a_failure_after_a_model_call_is_not_refunded(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure()
    _use(app, _Boom([_calls("c0")]))
    with signed_in(app, raise_server_exceptions=False) as client:
        assert [e["type"] for e in parse_sse(_send(client).text)][-3] == "error"
    assert _usage(quota_store) == 1
    assert quota_store.refunded == []


def test_a_resumable_provider_failure_is_not_refunded(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    """Refunding it too would let one count pay for any number of free resumes."""
    configure()
    _use(app, FlakyModel([reply("x", 1, 1)], fail_at=[0]))
    with signed_in(app, raise_server_exceptions=False) as client:
        assert [e["type"] for e in parse_sse(_send(client).text)][-3] == "turn_interrupted"
    assert _usage(quota_store) == 1
    assert quota_store.refunded == []


# --- configuration ---------------------------------------------------------------------------


def test_a_disabled_quota_never_counts_or_refuses(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure(enabled=False)
    _use(app, scripted(*["an answer"] * 10))
    with signed_in(app, raise_server_exceptions=False) as client:
        assert [_send(client, f"t{i}").status_code for i in range(LIMIT + 2)] == [200] * 4
    assert quota_store.calls == []


def test_an_exempt_admin_is_not_limited_but_a_user_is(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
    quota_store: InMemoryQuota,
) -> None:
    configure(admin_exempt=True)
    _use(app, scripted(*["an answer"] * 12))
    make_user(app)  # the first account is the one `keyed` gave a key
    make_user(app, "admin@example.com", admin=True)
    with signed_in(app, email="admin@example.com", raise_server_exceptions=False) as admin:
        keyed.give(KEY, asyncio.run(_id(app, "admin@example.com")))
        assert [_send(admin, f"a{i}").status_code for i in range(LIMIT + 2)] == [200] * 4
    assert quota_store.calls == []
    with signed_in(app, raise_server_exceptions=False) as user:
        assert [_send(user, f"u{i}").status_code for i in range(LIMIT + 1)] == [200, 200, 429]


def test_an_admin_is_counted_when_not_exempt(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
) -> None:
    configure(admin_exempt=False)
    _use(app, scripted(*["an answer"] * 12))
    make_user(app, "admin@example.com", admin=True)
    with signed_in(app, email="admin@example.com", raise_server_exceptions=False) as admin:
        keyed.give(KEY, asyncio.run(_id(app, "admin@example.com")))
        assert [_send(admin, f"a{i}").status_code for i in range(LIMIT + 1)] == [200, 200, 429]


async def _id(app: FastAPI, email: str) -> Any:  # noqa: ANN401
    user = await app.state.auth.accounts.users.by_email(email)
    assert user is not None
    return user.id


# --- the quota endpoint ----------------------------------------------------------------------


def test_the_endpoint_reports_the_users_figures(chat: TestClient) -> None:
    _send(chat, "t0")
    body = chat.get("/api/v1/usage/quota", headers=OWN).json()
    assert (body["applies"], body["limit"], body["used"], body["remaining"]) == (True, LIMIT, 1, 1)
    assert datetime.fromisoformat(body["resets_at"]).hour == 0


def test_the_endpoint_shows_nothing_of_another_user(
    app: FastAPI,
    keyed: KeyBench,
    configure: Callable[..., LimitSettings],
) -> None:
    configure()
    _use(app, scripted(*["an answer"] * 4))
    with signed_in(app, raise_server_exceptions=False) as first:
        _send(first)
    with signed_in(app, email="other@example.com") as second:
        body = second.get("/api/v1/usage/quota", headers=OWN).json()
    assert (body["used"], body["remaining"]) == (0, LIMIT)


def test_the_endpoint_says_the_quota_does_not_apply_to_an_exempt_admin(
    app: FastAPI,
    configure: Callable[..., LimitSettings],
) -> None:
    configure(admin_exempt=True)
    with signed_in(app, email="admin@example.com", admin=True) as admin:
        body = admin.get("/api/v1/usage/quota", headers=OWN).json()
    assert body == {
        "applies": False,
        "limit": None,
        "used": None,
        "remaining": None,
        "resets_at": None,
    }


def test_the_endpoint_needs_a_session(
    app: FastAPI,
    configure: Callable[..., LimitSettings],
) -> None:
    configure()
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        assert client.get("/api/v1/usage/quota", headers=OWN).status_code == 401
