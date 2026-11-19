"""Background jobs over the chat routes: cancel, the jobs of a snapshot, Clear workspace, the thread
stream's tenancy and reconnection, and the whole path (queued job, follow-up turn, quota)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from api.dependencies import AgentRuntime, get_runtime
from api.services.quota import QuotaService
from api.services.thread_events import thread_frames
from app.turns.thread_bus import MemoryThreadBus, thread_stream
from commons.stop import StopCheck
from config.limits import get_limit_settings
from storage.job_model import JobOutcome, JobStatus
from storage.turn_model import TurnStatus
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import OTHER_OWNER, OWNER, owned
from tests.fakes import InMemoryThreadStore, KeyBench, ScriptedChatModel, reply
from tests.fakes_quota import InMemoryQuota
from tools.jobs import heavy_submitter
from tools.schemas import JobResult

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "z9X8c7V6b5" * 3  # pragma: allowlist secret
BASE = "/api/v1/chat"
ARTIFACT: dict[str, list[object]] = {
    "assessed": [],
    "screened_out": [],
    "not_assessed": [],
    "worker_only": [],
}


@pytest.fixture
def keyed(store: KeyBench) -> KeyBench:
    store.give(KEY)
    return store


@pytest.fixture
def client(app: FastAPI, keyed: KeyBench) -> Iterator[TestClient]:
    model = ScriptedChatModel([reply("an answer", 1, 1) for _ in range(5)])
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with signed_in(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _job(threads: InMemoryThreadStore, thread: str = "j1", owner: Any = OWNER) -> str:
    async def make() -> str:
        await threads.touch(owned(thread, owner))
        job = await threads.jobs.create(owned(thread, owner), "assess_facilities", {}, 9)
        assert job is not None
        return job.id

    return asyncio.run(make())


def _status(threads: InMemoryThreadStore, job_id: str, owner: Any = OWNER) -> JobStatus:
    job = asyncio.run(threads.jobs.get(owner, job_id))
    assert job is not None
    return job.status


def _events(app: FastAPI, thread: str = "j1", owner: Any = OWNER) -> list[dict[str, object]]:
    bus: MemoryThreadBus = app.state.turn_queue.thread_bus
    stream = thread_stream(owned(thread, owner))
    return [record for _, record in asyncio.run(bus.read(stream, None, 0.01))]


# --- cancel -----------------------------------------------------------------------------------


def test_a_queued_job_is_cancelled_at_once_and_the_readers_are_told(
    client: TestClient,
    app: FastAPI,
    threads: InMemoryThreadStore,
) -> None:
    job_id = _job(threads)
    assert client.post(f"{BASE}/jobs/{job_id}/cancel", headers=OWN).status_code == 202
    assert _status(threads, job_id) is JobStatus.CANCELLED
    assert [(e["kind"], e["status"]) for e in _events(app)] == [("job.ended", "cancelled")]


def test_a_running_job_is_asked_to_stop(client: TestClient, threads: InMemoryThreadStore) -> None:
    job_id = _job(threads)
    asyncio.run(threads.jobs.claim(OWNER, job_id))
    assert client.post(f"{BASE}/jobs/{job_id}/cancel", headers=OWN).status_code == 202
    assert _status(threads, job_id) is JobStatus.RUNNING  # it stops after its current step
    assert asyncio.run(threads.jobs.cancel_requested(OWNER, job_id))


def test_an_ended_job_cannot_be_cancelled(client: TestClient, threads: InMemoryThreadStore) -> None:
    job_id = _job(threads)
    asyncio.run(threads.jobs.claim(OWNER, job_id))
    done = JobOutcome(JobStatus.SUCCEEDED, {"n": 1}, {"m": 1})
    asyncio.run(threads.jobs.finish(OWNER, job_id, done))
    response = client.post(f"{BASE}/jobs/{job_id}/cancel", headers=OWN)
    assert response.status_code == 409
    assert _status(threads, job_id) is JobStatus.SUCCEEDED


def test_another_users_or_an_unknown_job_is_404_and_stays_untouched(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    theirs = _job(threads, "j1", OTHER_OWNER)
    for job_id in (theirs, "f" * 32):
        assert client.post(f"{BASE}/jobs/{job_id}/cancel", headers=OWN).status_code == 404
    assert _status(threads, theirs, OTHER_OWNER) is JobStatus.QUEUED
    assert not asyncio.run(threads.jobs.cancel_requested(OTHER_OWNER, theirs))
    for bad in ("nope", "F" * 32, "a" * 31):
        assert client.post(f"{BASE}/jobs/{bad}/cancel", headers=OWN).status_code == 422


def test_cancel_needs_the_own_origin(client: TestClient, threads: InMemoryThreadStore) -> None:
    job_id = _job(threads)
    assert client.post(f"{BASE}/jobs/{job_id}/cancel").status_code == 403


# --- the snapshot and Clear workspace ---------------------------------------------------------


def test_the_snapshot_lists_the_jobs_with_position_and_no_result(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    first, second = _job(threads), _job(threads)
    asyncio.run(threads.jobs.claim(OWNER, first))
    done = JobOutcome(JobStatus.SUCCEEDED, {"secret": 42}, {"x": 1})
    asyncio.run(threads.jobs.finish(OWNER, first, done))
    body = client.get(f"{BASE}/threads/j1", headers=OWN).json()
    assert [(j["job_id"], j["status"]) for j in body["jobs"]] == [
        (first, "succeeded"),
        (second, "queued"),
    ]
    assert body["jobs"][1]["position"] == 0 and body["jobs"][0]["position"] is None
    assert set(body["jobs"][0]) == {
        "job_id",
        "tool",
        "status",
        "queued_at",
        "started_at",
        "ended_at",
        "position",
    }
    assert "secret" not in str(body)


def test_a_message_while_only_a_job_runs_is_not_409(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    job_id = _job(threads, "q1")
    asyncio.run(threads.jobs.claim(OWNER, job_id))
    body = {"thread_id": "q1", "message": "Meanwhile, what is a hazard quotient?"}
    assert client.post(f"{BASE}/stream", json=body, headers=OWN).status_code == 200


def test_clear_workspace_cancels_the_threads_open_jobs(
    client: TestClient,
    app: FastAPI,
    threads: InMemoryThreadStore,
) -> None:
    queued = _job(threads)
    assert client.delete(f"{BASE}/threads/j1", headers=OWN).status_code == 204
    assert [(e["kind"], e["job_id"]) for e in _events(app)] == [("job.ended", queued)]


def test_clear_workspace_leaves_other_threads_and_users_jobs_alone(
    client: TestClient,
    app: FastAPI,
    threads: InMemoryThreadStore,
) -> None:
    mine_elsewhere = _job(threads, "j2")
    theirs = _job(threads, "j1", OTHER_OWNER)
    _job(threads, "j1")
    assert client.delete(f"{BASE}/threads/j1", headers=OWN).status_code == 204
    assert _status(threads, mine_elsewhere) is JobStatus.QUEUED
    assert _status(threads, theirs, OTHER_OWNER) is JobStatus.QUEUED
    assert _events(app, "j1", OTHER_OWNER) == []


def test_a_busy_thread_is_not_cleared_and_its_jobs_stay(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    job_id = _job(threads)
    assert asyncio.run(threads.claim(owned("j1")))
    assert client.delete(f"{BASE}/threads/j1", headers=OWN).status_code == 409
    assert _status(threads, job_id) is JobStatus.QUEUED


# --- the thread stream ------------------------------------------------------------------------


def test_the_thread_stream_of_another_users_or_an_unknown_thread_is_404(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    asyncio.run(threads.touch(owned("theirs", OTHER_OWNER)))
    for thread in ("theirs", "nothing-here"):
        assert client.get(f"{BASE}/threads/{thread}/events", headers=OWN).status_code == 404


def test_a_malformed_last_event_id_is_422(client: TestClient, threads: InMemoryThreadStore) -> None:
    asyncio.run(threads.touch(owned("j1")))
    for bad in ("abc", "-1", "1.5", "1-2-3", "$"):
        headers = {**OWN, "Last-Event-ID": bad}
        assert client.get(f"{BASE}/threads/j1/events", headers=headers).status_code == 422


def test_the_route_reads_the_users_own_stream_from_the_last_event_id(
    client: TestClient,
    threads: InMemoryThreadStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(threads.touch(owned("j1")))
    seen: list[tuple[object, str | None]] = []

    async def frames(bus: object, key: object, after: str | None, block: float) -> Any:
        seen.append((key, after))
        yield "id: 4-0\ndata: {}\n\n"

    monkeypatch.setattr("api.routers.v1_chat.thread_frames", frames)
    headers = {**OWN, "Last-Event-ID": "3-0"}
    response = client.get(f"{BASE}/threads/j1/events", headers=headers)
    assert response.status_code == 200 and response.text == "id: 4-0\ndata: {}\n\n"
    assert seen == [(owned("j1"), "3-0")]  # the owner is the signed-in user


@pytest.mark.anyio
async def test_a_reconnecting_reader_gets_every_event_once_and_only_its_own_thread() -> None:
    bus = MemoryThreadBus()
    mine, theirs = owned("t"), owned("t", OTHER_OWNER)
    for n, kind in enumerate(["job.queued", "job.running", "job.ended"]):
        await bus.publish(thread_stream(mine), {"kind": kind, "job_id": "j", "status": "s"}, 60)
        await bus.publish(
            thread_stream(theirs),
            {"kind": "job.ended", "job_id": f"x{n}", "status": "s"},
            60,
        )
    await bus.publish(thread_stream(mine), {"kind": "bogus", "status": "s"}, 60)  # not the contract
    frames = thread_frames(bus, mine, None, 0.05)
    first = [await anext(frames) for _ in range(2)]
    await frames.aclose()
    last_id = first[-1].split("\n")[0].removeprefix("id: ")
    again = thread_frames(bus, mine, last_id, 0.05)
    rest = await anext(again)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(again), 0.2)  # nothing more, and nothing repeated
    await again.aclose()
    assert [f.split("\n")[1] for f in first + [rest]] == [
        'data: {"kind":"job.queued","job_id":"j","status":"s"}',
        'data: {"kind":"job.running","job_id":"j","status":"s"}',
        'data: {"kind":"job.ended","job_id":"j","status":"s"}',
    ]
    assert "x0" not in "".join(first + [rest])  # another user's thread never appears


# --- the whole path ---------------------------------------------------------------------------


@tool(response_format="content_and_artifact")
def assess_facilities(cas_number: str, *, config: RunnableConfig) -> Any:
    """Assess the facilities of a chemical.

    Args:
        cas_number: A CAS number.
    """
    raise AssertionError("a heavy tool never runs inside the turn")


def _run_job(arguments: Mapping[str, object], should_stop: StopCheck) -> JobResult:
    return {"assessed": 1}, ARTIFACT


def _wait(condition: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert condition()


def _turns(threads: InMemoryThreadStore) -> list[Any]:
    return list(threads.turns._turns.values())  # pyright: ignore[reportPrivateUsage]


def test_a_queued_job_ends_and_its_follow_up_runs_without_counting_against_the_quota(
    app: FastAPI,
    keyed: KeyBench,
    threads: InMemoryThreadStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitter = heavy_submitter(assess_facilities, lambda arguments, config: None)
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [submitter])
    monkeypatch.setattr("api.dependencies.job_runners", lambda: {"assess_facilities": _run_job})
    call = ToolCall(name="assess_facilities", args={"cas_number": "110-54-3"}, id="c1")
    model = ScriptedChatModel(
        [
            AIMessage(content="", tool_calls=[call]),
            reply("The assessment is started.", 3, 2),
            reply("It found one facility.", 3, 2),
        ],
    )
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    store = InMemoryQuota()
    app.state.quota = QuotaService(store, replace(get_limit_settings(), daily_turns_per_user=1))
    with signed_in(app, raise_server_exceptions=False) as client:
        body = {"thread_id": "q1", "message": "Assess hexane"}
        assert client.post(f"{BASE}/stream", json=body, headers=OWN).status_code == 200
        _wait(lambda: sum(1 for t in _turns(threads) if t.status is TurnStatus.COMPLETED) == 2)
        follow_ups = [t for t in _turns(threads) if t.automatic]
        assert len(follow_ups) == 1 and follow_ups[0].planned.counted is False
        (job,) = asyncio.run(threads.jobs.for_thread(owned("q1")))
        assert job.status is JobStatus.SUCCEEDED and job.owner_id == OWNER
        assert asyncio.run(store.usage(OWNER)) == 1  # the user's one turn; the follow-up is free
        stored = asyncio.run(threads.tool_messages(owned("q1")))
        assert [m.type for m in stored] == ["ai", "tool", "ai", "tool"]
        assert (
            getattr(stored[-1], "artifact", None) == ARTIFACT
        )  # the workspace fills from the job's artifact
        snapshot = client.get(f"{BASE}/threads/q1", headers=OWN).json()
        assert [m["role"] for m in snapshot["messages"]] == ["user", "assistant", "assistant"]
        assert snapshot["messages"][-1]["text"] == "It found one facility."
        assert [j["status"] for j in snapshot["jobs"]] == ["succeeded"]
        refused = client.post(f"{BASE}/stream", json={**body, "thread_id": "q2"}, headers=OWN)
        assert refused.status_code == 429  # the limit is still reached by the user's own turns
    kinds = [e["kind"] for e in _events(app, "q1")]
    assert kinds.count("job.queued") == kinds.count("job.ended") == 1
    assert kinds.count("turn.started") == kinds.count("turn.ended") == 2
