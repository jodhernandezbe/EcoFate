"""Tests for the thread report route: status codes, attachment, and nothing run or leaked."""

from __future__ import annotations

import asyncio
import zipfile
from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import AgentRuntime, get_runtime
from api.schemas.workspace import WorkspaceState
from api.services.report.builder import MEDIA_TYPE
from api.services.threads import ThreadStore
from tests.api.conftest import ORIGIN
from tests.api.services.report.fixtures import assessed, lines, load
from tests.fakes import OPENAI_ENTRY, FakeCredentialStore, scripted

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "q1W2e3R4t5" * 3  # pragma: allowlist secret
URL = "/api/v1/chat/threads/{}/report"


@pytest.fixture
def chat(app: FastAPI, store: FakeCredentialStore) -> Iterator[TestClient]:
    store.entries[OPENAI_ENTRY] = KEY
    model = scripted("The **assistant** answer.")
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client


def _threads(app: FastAPI) -> ThreadStore:
    return app.state.threads


def _assessed_thread(chat: TestClient, app: FastAPI, thread: str = "t1") -> None:
    body = {"thread_id": thread, "message": "assess"}
    assert chat.post("/api/v1/chat/stream", json=body, headers=OWN).status_code == 200
    asyncio.run(_threads(app).set_workspace(thread, assessed()))


def _refuse_model(app: FastAPI) -> None:
    def factory(key: str) -> None:
        raise AssertionError("the report must not build a chat model")

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(factory, 10)  # pyright: ignore[reportArgumentType]


def test_report_of_an_assessed_thread(chat: TestClient, app: FastAPI) -> None:
    _assessed_thread(chat, app)
    _refuse_model(app)
    response = chat.get(URL.format("t1"), headers=OWN)
    assert response.status_code == 200
    assert response.headers["content-type"] == MEDIA_TYPE
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;") and disposition.endswith('.docx"')
    text = lines(load(response.content))
    assert "The assistant answer." in text


def test_report_contains_no_key_material(chat: TestClient, app: FastAPI) -> None:
    _assessed_thread(chat, app)
    response = chat.get(URL.format("t1"), headers=OWN)
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        xml = b"".join(archive.read(name) for name in archive.namelist())
    assert KEY.encode() not in xml
    assert b"sk-proj-" not in xml
    assert b"Origin" not in xml


def test_unknown_thread_is_a_generic_404(chat: TestClient) -> None:
    response = chat.get(URL.format("nope"), headers=OWN)
    assert response.status_code == 404
    assert set(response.json()) == {"error", "correlation_id"}


def test_empty_thread_is_409(chat: TestClient, app: FastAPI) -> None:
    body = {"thread_id": "t1", "message": "hello"}
    chat.post("/api/v1/chat/stream", json=body, headers=OWN)
    asyncio.run(_threads(app).set_workspace("t1", WorkspaceState()))
    response = chat.get(URL.format("t1"), headers=OWN)
    assert response.status_code == 409
    assert set(response.json()) == {"error", "correlation_id"}


def test_running_thread_is_409_and_left_running(chat: TestClient, app: FastAPI) -> None:
    _assessed_thread(chat, app)
    threads = _threads(app)
    asyncio.run(threads.claim("t1"))
    assert chat.get(URL.format("t1"), headers=OWN).status_code == 409
    assert asyncio.run(threads.running("t1"))
    asyncio.run(threads.release("t1"))


def test_malformed_id_is_422(chat: TestClient) -> None:
    assert chat.get(URL.format("a%20b"), headers=OWN).status_code == 422


def test_report_does_not_change_the_thread(chat: TestClient, app: FastAPI) -> None:
    _assessed_thread(chat, app)
    before = chat.get("/api/v1/chat/threads/t1", headers=OWN).json()
    chat.get(URL.format("t1"), headers=OWN)
    assert chat.get("/api/v1/chat/threads/t1", headers=OWN).json() == before
