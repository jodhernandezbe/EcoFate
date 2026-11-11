"""Tests for answering an open confirmation request over the chat routes."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import AgentRuntime, get_runtime
from api.services.threads import ThreadStore
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import owned
from tests.api.streams import parse_sse
from tests.fakes import KeyBench, scripted
from tools.schemas import ConfirmationRequest, MissingEntry

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "r4T5y6U7i8" * 3  # pragma: allowlist secret
IUR = "iur:71-43-2"


@pytest.fixture
def chat(app: FastAPI, store: KeyBench) -> Iterator[TestClient]:
    store.give(KEY)
    model = scripted("the answer with the value", "another answer")
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with signed_in(app, raise_server_exceptions=False) as client:
        yield client


def _open(threads: ThreadStore) -> None:
    entry = MissingEntry(
        entry_id=IUR,
        quantity="iur",
        subject="71-43-2",
        accepted_units=["1/(ug/m^3)", "1/(mg/m^3)"],
        minimum=1e-9,
        maximum=1000.0,
        purpose="the cancer risk",
    )
    asyncio.run(threads.touch(owned("t1")))
    asyncio.run(
        threads.set_pending(owned("t1"), ConfirmationRequest(request_id="req1", entries=[entry])),
    )


def _answer(request_id: str, entries: list[dict[str, object]]) -> dict[str, object]:
    return {"thread_id": "t1", "answers": {"request_id": request_id, "entries": entries}}


def _supply(number: float) -> dict[str, object]:
    return {"entry_id": IUR, "decision": "supply", "number": number, "unit": "1/(mg/m^3)"}


def test_valid_answer_starts_the_next_turn_and_closes_the_request(
    chat: TestClient,
    app: FastAPI,
) -> None:
    threads: ThreadStore = app.state.threads
    _open(threads)
    response = chat.post("/api/v1/chat/stream", json=_answer("req1", [_supply(0.002)]), headers=OWN)
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[-1]["type"] == "turn_finished"
    assert asyncio.run(threads.pending(owned("t1"))) is None
    assert asyncio.run(threads.answers(owned("t1")))[0][IUR] == pytest.approx(2e-6)


def test_answer_for_a_closed_request_is_409_and_nothing_starts(
    chat: TestClient,
    app: FastAPI,
) -> None:
    threads: ThreadStore = app.state.threads
    response = chat.post("/api/v1/chat/stream", json=_answer("req1", [_supply(0.002)]), headers=OWN)
    assert response.status_code == 409
    assert asyncio.run(threads.answers(owned("t1"))) == ({}, frozenset())


def test_rejected_value_keeps_the_request_open(chat: TestClient, app: FastAPI) -> None:
    threads: ThreadStore = app.state.threads
    _open(threads)
    response = chat.post("/api/v1/chat/stream", json=_answer("req1", [_supply(-1.0)]), headers=OWN)
    assert response.status_code == 422
    assert asyncio.run(threads.pending(owned("t1"))) is not None
    assert asyncio.run(threads.claim(owned("t1")))  # the rejected reply left the thread idle


def test_answer_naming_a_value_not_asked_is_422(chat: TestClient, app: FastAPI) -> None:
    threads: ThreadStore = app.state.threads
    _open(threads)
    other: dict[str, object] = {"entry_id": "rfc:other", "decision": "decline"}
    response = chat.post("/api/v1/chat/stream", json=_answer("req1", [other]), headers=OWN)
    assert response.status_code == 422
    assert asyncio.run(threads.pending(owned("t1"))) is not None


def test_snapshot_shows_the_open_request_after_a_reload(chat: TestClient, app: FastAPI) -> None:
    _open(app.state.threads)
    snapshot = chat.get("/api/v1/chat/threads/t1", headers=OWN)
    assert snapshot.status_code == 200
    prompt = snapshot.json()["confirmation"]
    assert prompt["request_id"] == "req1"
    assert prompt["entries"][0]["entry_id"] == IUR
