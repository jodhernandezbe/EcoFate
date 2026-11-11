"""Interrupted turns over HTTP: the turn record, the resume endpoint, abandoning, recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolCall
from langchain_core.tools import tool
from pydantic import PrivateAttr

from api.dependencies import AgentRuntime, get_runtime
from api.schemas.chat import ChatRequest
from api.services import provider_errors
from api.services.key_setup import turn_key_loader
from api.services.turn_lifecycle import BUSY, NOTHING_TO_RESUME, RESUME_CAP
from storage.turn_model import Turn, TurnStatus
from tests.api.auth_support import build_app
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import OWNER, owned
from tests.api.streams import begun_turn, parse_sse
from tests.fakes import (
    InMemoryThreadStore,
    KeyBench,
    ScriptedChatModel,
    reply,
)

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "q1W2e3R4t5" * 3  # pragma: allowlist secret
THREAD = "r1"
RUNS: list[str] = []


@tool
def lookup(cas_number: str) -> str:
    """Look up a CAS number."""
    RUNS.append(cas_number)
    return f"found {cas_number}"


class QuotaError(Exception):
    """Stands in for the provider's 429 ``insufficient_quota`` (status and code only)."""

    status_code = 429
    body: dict[str, object] = {"error": {"code": "insufficient_quota"}}  # noqa: RUF012 - stand-in


class FlakyModel(ScriptedChatModel):
    """A scripted model that raises ``error`` on the given calls (0-based); an index listed
    twice fails twice (a resume retries the call that failed)."""

    _fail_at: list[int] = PrivateAttr(default_factory=list[int])
    _error: Exception = PrivateAttr(default_factory=lambda: QuotaError("raw provider text"))

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

    def _next(self, messages: list[BaseMessage] | None = None) -> AIMessage:
        if self._cursor in self._fail_at:
            self._fail_at.remove(self._cursor)
            raise self._error
        return super()._next(messages)


def _calls(*ids: str) -> AIMessage:
    calls = [ToolCall(name="lookup", args={"cas_number": f"cas-{i}"}, id=i) for i in ids]
    return AIMessage(content="", tool_calls=calls)


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    RUNS.clear()
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup])


@pytest.fixture
def keyed(store: KeyBench) -> KeyBench:
    store.give(KEY)
    return store


def _client(app: FastAPI, model: ScriptedChatModel, max_resumes: int = 3) -> TestClient:
    runtime = AgentRuntime(lambda key: model, 10, max_resumes_per_turn=max_resumes)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return signed_in(app, raise_server_exceptions=False)


@pytest.fixture
def flaky(app: FastAPI, keyed: KeyBench) -> Iterator[TestClient]:
    """No credits on the second model call: after tool c0 ran, before the next step."""
    model = FlakyModel([_calls("c0"), _calls("c1"), reply("All done", 2, 1)], fail_at=[1])
    with _client(app, model) as client:
        yield client


def _send(client: TestClient, message: str = "Assess 1-1-1") -> Response:
    body = {"thread_id": THREAD, "message": message}
    return client.post("/api/v1/chat/stream", json=body, headers=OWN)


def _resume(client: TestClient, thread: str = THREAD) -> Response:
    return client.post(f"/api/v1/chat/threads/{thread}/resume", headers=OWN)


def _latest(app: FastAPI, thread: str = THREAD) -> Turn | None:
    return asyncio.run(app.state.threads.turns.latest(owned(thread)))


def _types(response: Response) -> list[str]:
    return [event["type"] for event in parse_sse(response.text)]


def _interrupted_turn(app: FastAPI, *, resumes: int = 0, reason: str = "out_of_credits") -> Turn:
    """A thread whose latest turn is interrupted (with no checkpoint unless a turn ran)."""
    threads: InMemoryThreadStore = app.state.threads

    async def make() -> Turn:
        await threads.touch(owned(THREAD))
        turn = await threads.turns.begin(owned(THREAD))
        assert turn is not None
        turn = await threads.turns.move(OWNER, turn.id, TurnStatus.INTERRUPTED, reason)
        for _ in range(resumes):
            assert await threads.turns.resume(OWNER, turn.id, 99) is not None
            turn = await threads.turns.move(OWNER, turn.id, TurnStatus.INTERRUPTED, reason)
        return turn

    return asyncio.run(make())


# --- interruption ---------------------------------------------------------------------------


def test_no_credits_interrupts_the_turn_and_keeps_its_finished_tools(
    flaky: TestClient,
    app: FastAPI,
) -> None:
    events = parse_sse(_send(flaky).text)
    assert [e["type"] for e in events][-3:] == ["turn_interrupted", "usage", "turn_finished"]
    interrupted = events[-3]
    assert (interrupted["reason"], interrupted["resumable"]) == ("out_of_credits", True)
    assert interrupted["message"] == provider_errors.OUT_OF_CREDITS
    assert "raw provider text" not in str(events)
    turn = _latest(app)
    assert turn is not None and events[0]["turn_id"] == turn.id
    assert (turn.status, turn.reason) == (TurnStatus.INTERRUPTED, "out_of_credits")
    assert RUNS == ["cas-c0"]


def test_the_snapshot_reports_the_interruption(flaky: TestClient) -> None:
    _send(flaky)
    snapshot = flaky.get(f"/api/v1/chat/threads/{THREAD}", headers=OWN).json()
    assert snapshot["interrupted"] == {
        "reason": "out_of_credits",
        "resumable": True,
        "message": provider_errors.OUT_OF_CREDITS,
    }


def test_the_step_limit_interrupts_the_turn(app: FastAPI, keyed: KeyBench) -> None:
    model = ScriptedChatModel([_calls("a"), _calls("b"), _calls("c"), reply("x", 1, 1)])
    runtime = AgentRuntime(lambda key: model, 2)
    app.dependency_overrides[get_runtime] = lambda: runtime
    with signed_in(app, raise_server_exceptions=False) as client:
        events = parse_sse(_send(client).text)
    interrupted = next(e for e in events if e["type"] == "turn_interrupted")
    assert (interrupted["reason"], interrupted["resumable"]) == ("step_limit", True)
    turn = _latest(app)
    assert turn is not None and (turn.status, turn.reason) == (TurnStatus.INTERRUPTED, "step_limit")


def test_an_unexpected_failure_fails_the_turn_and_offers_no_resume(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    model = FlakyModel([reply("x", 1, 1)], fail_at=[0], error=RuntimeError("boom"))
    with _client(app, model) as client:
        assert _types(_send(client))[-3:] == ["error", "usage", "turn_finished"]
        snapshot = client.get(f"/api/v1/chat/threads/{THREAD}", headers=OWN).json()
        assert snapshot["interrupted"] is None
        assert _resume(client).status_code == 409
    turn = _latest(app)
    assert turn is not None and (turn.status, turn.reason) == (TurnStatus.FAILED, "unexpected")


def test_a_turn_that_answers_is_completed(app: FastAPI, keyed: KeyBench) -> None:
    with _client(app, ScriptedChatModel([reply("hello", 1, 1)])) as client:
        assert _types(_send(client))[-1] == "turn_finished"
        assert (
            client.get(f"/api/v1/chat/threads/{THREAD}", headers=OWN).json()["interrupted"] is None
        )
    turn = _latest(app)
    assert turn is not None and turn.status is TurnStatus.COMPLETED and turn.finished_at


# --- resume ---------------------------------------------------------------------------------


def test_resume_streams_only_the_rest_of_the_turn(flaky: TestClient, app: FastAPI) -> None:
    first = parse_sse(_send(flaky).text)
    response = _resume(flaky)
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[0]["type"] == "turn_started" and events[0]["resumed"] is True
    assert events[0]["turn_id"] == first[0]["turn_id"]
    statuses = [(e["call_id"], e["phase"]) for e in events if e["type"] == "tool_status"]
    assert statuses == [("c1", "started"), ("c1", "finished")]  # c0 is not run or shown again
    assert "".join(e["text"] for e in events if e["type"] == "token") == "All done"
    assert [e["type"] for e in events][-2:] == ["usage", "turn_finished"]
    assert RUNS == ["cas-c0", "cas-c1"]
    turn = _latest(app)
    assert turn is not None and (turn.status, turn.resume_count) == (TurnStatus.COMPLETED, 1)
    assert flaky.get(f"/api/v1/chat/threads/{THREAD}", headers=OWN).json()["interrupted"] is None


def test_the_resumed_message_is_not_sent_again(flaky: TestClient, app: FastAPI) -> None:
    _send(flaky)
    _resume(flaky)
    messages = asyncio.run(app.state.threads.messages(owned(THREAD)))
    assert [m.content for m in messages if isinstance(m, HumanMessage)] == ["Assess 1-1-1"]


def test_resumed_usage_is_added_to_the_same_turn(flaky: TestClient) -> None:
    first = parse_sse(_send(flaky).text)[-2]
    resumed = parse_sse(_resume(flaky).text)[-2]
    assert resumed["turn"]["calls"] == first["turn"]["calls"] + 2  # c1, then the answer
    assert resumed["session"]["calls"] == resumed["turn"]["calls"]


def test_an_interruption_at_the_cap_is_not_resumable(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    model = FlakyModel([_calls("c0"), reply("done", 1, 1)], fail_at=[1, 1])
    with _client(app, model, max_resumes=1) as client:
        _send(client)
        events = parse_sse(_resume(client).text)  # the resume runs out of credits again
        interrupted = next(e for e in events if e["type"] == "turn_interrupted")
        assert interrupted["resumable"] is False
        assert interrupted["message"] == provider_errors.NOT_RESUMABLE
        response = _resume(client)
    assert (response.status_code, response.json()["error"]) == (409, RESUME_CAP)


# --- refused resumes change nothing ---------------------------------------------------------


def test_resume_of_an_unknown_thread_is_404(flaky: TestClient) -> None:
    assert _resume(flaky, "never-seen").status_code == 404


def test_resume_of_a_malformed_id_is_422(flaky: TestClient) -> None:
    assert _resume(flaky, "bad%20id").status_code == 422


def test_resume_of_a_completed_turn_is_409_and_changes_nothing(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    with _client(app, ScriptedChatModel([reply("hello", 1, 1)])) as client:
        _send(client)
        before = _latest(app)
        response = _resume(client)
    assert (response.status_code, response.json()["error"]) == (409, NOTHING_TO_RESUME)
    assert _latest(app) == before


def test_resume_past_the_cap_is_409_and_changes_nothing(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    turn = _interrupted_turn(app, resumes=3)
    with _client(app, ScriptedChatModel([]), max_resumes=3) as client:
        response = _resume(client)
    assert (response.status_code, response.json()["error"]) == (409, RESUME_CAP)
    assert _latest(app) == turn


def test_resume_while_a_turn_runs_is_409_and_leaves_it_running(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    turn = _interrupted_turn(app)
    asyncio.run(app.state.threads.claim(owned(THREAD)))
    with _client(app, ScriptedChatModel([])) as client:
        response = _resume(client)
    assert (response.status_code, response.json()["error"]) == (409, BUSY)
    assert _latest(app) == turn
    assert asyncio.run(app.state.threads.running(owned(THREAD)))


def test_resume_without_a_key_is_409_and_changes_nothing(app: FastAPI) -> None:
    turn = _interrupted_turn(app)
    with _client(app, ScriptedChatModel([])) as client:
        response = _resume(client)
    assert (response.status_code, response.json()["error"]) == (409, provider_errors.NO_KEY_MESSAGE)
    assert _latest(app) == turn
    assert not asyncio.run(app.state.threads.running(owned(THREAD)))  # the lease was given back


def test_resume_with_nothing_left_to_run_completes_the_turn_and_is_409(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    _interrupted_turn(app)  # no checkpoint: nothing would run next
    with _client(app, ScriptedChatModel([])) as client:
        response = _resume(client)
    assert (response.status_code, response.json()["error"]) == (409, NOTHING_TO_RESUME)
    turn = _latest(app)
    assert turn is not None and turn.status is TurnStatus.COMPLETED


def test_an_unknown_stored_reason_is_not_resumable(
    app: FastAPI,
    keyed: KeyBench,
) -> None:
    turn = _interrupted_turn(app, reason="something_new")
    with _client(app, ScriptedChatModel([])) as client:
        assert (
            client.get(f"/api/v1/chat/threads/{THREAD}", headers=OWN).json()["interrupted"] is None
        )
        assert _resume(client).status_code == 409
    assert _latest(app) == turn


# --- abandoning, leaving, restarting --------------------------------------------------------


def test_a_new_message_supersedes_the_interrupted_turn(flaky: TestClient, app: FastAPI) -> None:
    first = parse_sse(_send(flaky).text)[0]["turn_id"]
    assert _types(_send(flaky, "Something else"))[-1] == "turn_finished"
    old = asyncio.run(_old_turn(app, first))
    assert (old.status, old.reason) == (TurnStatus.FAILED, "superseded")
    latest = _latest(app)
    assert latest is not None and latest.id != first


async def _old_turn(app: FastAPI, turn_id: str) -> Turn:
    store: InMemoryThreadStore = app.state.threads
    return next(t for t in store.turns._turns.values() if t.id == turn_id)  # pyright: ignore[reportPrivateUsage]


def test_a_client_that_leaves_the_stream_does_not_stop_its_turn(keyed: KeyBench) -> None:
    threads = InMemoryThreadStore()
    runtime = AgentRuntime(lambda key: ScriptedChatModel([reply("done", 1, 1)]), 10)

    async def scenario() -> Turn | None:
        assert await threads.claim(owned(THREAD))
        request = ChatRequest(thread_id=THREAD, message="go")
        loader = turn_key_loader(keyed.services, OWNER)
        events = begun_turn(request, threads=threads, runtime=runtime, keys=loader)
        await anext(events)
        await events.aclose()  # the client went away mid-stream; the worker keeps going
        for _ in range(200):
            latest = await threads.turns.latest(owned(THREAD))
            if latest is not None and latest.status is TurnStatus.COMPLETED:
                break
            await asyncio.sleep(0.01)
        assert not await threads.running(owned(THREAD))  # released by the worker at the end
        return await threads.turns.latest(owned(THREAD))

    turn = asyncio.run(scenario())
    assert turn is not None and (turn.status, turn.reason) == (TurnStatus.COMPLETED, None)


def test_turns_left_running_are_interrupted_at_start_up(store: KeyBench) -> None:
    threads = InMemoryThreadStore()
    asyncio.run(threads.touch(owned(THREAD)))
    left = asyncio.run(threads.turns.begin(owned(THREAD)))
    assert left is not None
    app = build_app(threads=threads, keys=store.services)
    with signed_in(app, raise_server_exceptions=False) as client:
        turn = _latest(app)
        assert turn is not None and (turn.status, turn.reason) == (
            TurnStatus.INTERRUPTED,
            "worker_lost",
        )
        snapshot: dict[str, Any] = client.get(f"/api/v1/chat/threads/{THREAD}", headers=OWN).json()
    assert snapshot["interrupted"]["reason"] == "worker_lost"
    assert snapshot["interrupted"]["resumable"] is True
    assert asyncio.run(threads.turns.begin(owned(THREAD))) is not None  # the thread is not blocked
