"""The chat routes over the turn queue: enqueue (never run here), 503, reattach, cancel and the
running turn in the snapshot."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from api.dependencies import AgentRuntime, get_runtime
from api.main import queue_setup
from api.services.turn_queue import EVENTS_EXPIRED, UNAVAILABLE, QueueSetup
from app.task_queue import EnqueueError, TurnJob
from app.turns.bus import MemoryBus
from storage.turn_model import Turn, TurnStatus
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import OTHER_OWNER, OWNER, owned
from tests.api.streams import parse_sse
from tests.fakes import InMemoryThreadStore, KeyBench, scripted

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "q0U1e2U3e4" * 3  # pragma: allowlist secret
MESSAGE = "Assess benzene near my plant"


class LostWorker:
    """Records each job and then behaves like a worker that died at once: its turn is left
    interrupted (``worker_lost``) without a single event."""

    def __init__(self, threads: InMemoryThreadStore) -> None:
        self.threads = threads
        self.jobs: list[TurnJob] = []

    async def enqueue(self, job: TurnJob) -> None:
        self.jobs.append(job)
        await self.threads.turns.abandon(job.owner_id, job.turn_id, "worker_lost")
        await self.threads.release(owned("q1", job.owner_id))


class DownBroker:
    """Redis does not answer."""

    async def enqueue(self, job: TurnJob) -> None:
        raise EnqueueError("ConnectionError")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _never_built(key: SecretStr) -> BaseChatModel:
    raise AssertionError("the API process must not build a chat model")


def _fast(setup: QueueSetup) -> QueueSetup:
    return replace(setup, timing=replace(setup.timing, block_seconds=0.05, grace_seconds=0.05))


def _use(app: FastAPI, setup: QueueSetup) -> None:
    app.state.turn_queue = _fast(setup)


def _post(client: TestClient, thread: str = "q1") -> Response:
    return client.post(
        "/api/v1/chat/stream",
        json={"thread_id": thread, "message": MESSAGE},
        headers=OWN,
    )


@pytest.fixture
def keyed(store: KeyBench) -> KeyBench:
    store.give(KEY)
    return store


@pytest.fixture
def client(app: FastAPI, keyed: KeyBench) -> Iterator[TestClient]:
    model = scripted("an answer")
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with signed_in(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _latest(threads: InMemoryThreadStore, thread: str = "q1") -> Turn:
    turn = asyncio.run(threads.turns.latest(owned(thread)))
    assert turn is not None
    return turn


# --- enqueue --------------------------------------------------------------------------------


def test_a_turn_is_queued_with_ids_only_and_the_api_builds_no_model(
    app: FastAPI,
    keyed: KeyBench,
    threads: InMemoryThreadStore,
) -> None:
    worker = LostWorker(threads)
    _use(app, queue_setup(MemoryBus(), worker))
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(_never_built, 10)
    with signed_in(app, raise_server_exceptions=False) as client:
        response = _post(client)
    turn = _latest(threads)
    assert worker.jobs == [TurnJob(turn.id, OWNER)]
    assert turn.planned is not None and turn.planned.question == MESSAGE  # in the database
    events = parse_sse(response.text)
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["turn_started", "turn_status"] and events[1]["phase"] == "queued"
    interrupted = next(e for e in events if e["type"] == "turn_interrupted")
    assert (interrupted["reason"], interrupted["resumable"]) == ("worker_lost", True)
    assert kinds[-2:] == ["usage", "turn_finished"]


def test_an_unreachable_queue_answers_503_and_fails_the_turn(
    app: FastAPI,
    keyed: KeyBench,
    threads: InMemoryThreadStore,
) -> None:
    _use(app, queue_setup(MemoryBus(), DownBroker()))
    with signed_in(app, raise_server_exceptions=False) as client:
        response = _post(client)
    assert (response.status_code, response.json()["error"]) == (503, UNAVAILABLE)
    turn = _latest(threads)
    assert (turn.status, turn.reason) == (TurnStatus.FAILED, "unexpected")
    assert not asyncio.run(threads.running(owned("q1")))  # the thread is free again


# --- reattach -------------------------------------------------------------------------------


def test_reattaching_after_a_seq_sends_only_the_later_events(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    first = parse_sse(_post(client).text)
    turn_id = first[0]["turn_id"]
    whole = parse_sse(client.get(f"/api/v1/chat/turns/{turn_id}/events", headers=OWN).text)
    assert whole == first
    cut = first[4]["seq"]
    headers = {**OWN, "Last-Event-ID": str(cut)}
    rest = parse_sse(client.get(f"/api/v1/chat/turns/{turn_id}/events", headers=headers).text)
    assert rest == [e for e in first if e["seq"] > cut]
    assert rest[-1]["type"] == "turn_finished"


def test_reattaching_to_expired_events_is_410(
    app: FastAPI,
    client: TestClient,
) -> None:
    clock = Clock()
    _use(app, queue_setup(MemoryBus(clock), None))
    turn_id = parse_sse(_post(client).text)[0]["turn_id"]
    clock.now += 10**6
    response = client.get(f"/api/v1/chat/turns/{turn_id}/events", headers=OWN)
    assert (response.status_code, response.json()["error"]) == (410, EVENTS_EXPIRED)


def test_another_users_or_an_unknown_turn_is_404_and_a_malformed_id_422(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    theirs = asyncio.run(threads.turns.begin(owned("q1", OTHER_OWNER)))
    assert theirs is not None
    for turn_id in (theirs.id, "f" * 32):
        assert client.get(f"/api/v1/chat/turns/{turn_id}/events", headers=OWN).status_code == 404
        assert client.post(f"/api/v1/chat/turns/{turn_id}/cancel", headers=OWN).status_code == 404
    for bad in ("not-a-turn", "F" * 32, "a" * 31):
        assert client.get(f"/api/v1/chat/turns/{bad}/events", headers=OWN).status_code == 422
        assert client.post(f"/api/v1/chat/turns/{bad}/cancel", headers=OWN).status_code == 422
    assert not asyncio.run(threads.turns.cancel_requested(OTHER_OWNER, theirs.id))


def test_a_malformed_last_event_id_is_422(client: TestClient) -> None:
    turn_id = parse_sse(_post(client).text)[0]["turn_id"]
    for bad in ("-1", "abc", "1.5"):
        headers = {**OWN, "Last-Event-ID": bad}
        response = client.get(f"/api/v1/chat/turns/{turn_id}/events", headers=headers)
        assert response.status_code == 422


# --- cancel ---------------------------------------------------------------------------------


def test_cancelling_an_open_turn_is_accepted_and_a_finished_one_refused(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    queued = asyncio.run(threads.turns.begin(owned("q2")))
    assert queued is not None
    assert client.post(f"/api/v1/chat/turns/{queued.id}/cancel", headers=OWN).status_code == 202
    assert asyncio.run(threads.turns.cancel_requested(OWNER, queued.id))
    finished = parse_sse(_post(client).text)[0]["turn_id"]
    before = _latest(threads)
    response = client.post(f"/api/v1/chat/turns/{finished}/cancel", headers=OWN)
    assert response.status_code == 409
    assert _latest(threads) == before  # unchanged


def test_cancel_needs_the_own_origin(client: TestClient, threads: InMemoryThreadStore) -> None:
    queued = asyncio.run(threads.turns.begin(owned("q2")))
    assert queued is not None
    assert client.post(f"/api/v1/chat/turns/{queued.id}/cancel").status_code == 403


# --- snapshot -------------------------------------------------------------------------------


def test_the_snapshot_names_a_queued_or_running_turn_only(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    parse_sse(_post(client).text)
    assert client.get("/api/v1/chat/threads/q1", headers=OWN).json()["running_turn"] is None
    asyncio.run(threads.touch(owned("q3")))
    queued = asyncio.run(threads.turns.begin(owned("q3")))
    assert queued is not None
    snapshot = client.get("/api/v1/chat/threads/q3", headers=OWN).json()
    assert snapshot["running_turn"] == {"turn_id": queued.id, "resumed": False, "question": None}


# --- the current thread ---------------------------------------------------------------------


def test_the_current_thread_is_the_users_most_recently_used(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    assert client.get("/api/v1/chat/current-thread", headers=OWN).status_code == 404
    parse_sse(_post(client, "older").text)
    parse_sse(_post(client, "newer").text)
    current = client.get("/api/v1/chat/current-thread", headers=OWN).json()
    assert current["thread_id"] == "newer"
    assert current["messages"][0] == {"role": "user", "text": MESSAGE}
    assert current["running_turn"] is None


def test_another_users_thread_is_never_current(
    client: TestClient,
    threads: InMemoryThreadStore,
) -> None:
    asyncio.run(threads.touch(owned("theirs", OTHER_OWNER)))
    assert client.get("/api/v1/chat/current-thread", headers=OWN).status_code == 404
