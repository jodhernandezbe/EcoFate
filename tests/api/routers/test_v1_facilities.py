"""The facility route serves only what the thread's workspace holds."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_threads
from api.services.state_serializer import build_workspace
from api.services.threads import ThreadStore
from tests.api.conftest import signed_in
from tests.api.keys import owned
from tests.api.services.projectors.factories import RULES, inventory, record
from tests.fakes import InMemoryThreadStore


def _client(app: FastAPI, threads: ThreadStore) -> TestClient:
    app.dependency_overrides[get_threads] = lambda: threads
    return signed_in(app)


def _threads_with_facility() -> ThreadStore:
    threads = InMemoryThreadStore()
    asyncio.run(threads.set_workspace(owned("t1"), build_workspace(inventory(record("A")), RULES)))
    return threads


def test_returns_the_facility_of_the_thread(app: FastAPI) -> None:
    body = _client(app, _threads_with_facility()).get(
        "/api/v1/facilities/A",
        params={"thread_id": "t1"},
    )
    assert body.status_code == 200
    assert body.json()["frs_id"] == "A"
    assert body.json()["name"] == "Plant A"


def test_an_unknown_facility_is_404(app: FastAPI) -> None:
    response = _client(app, _threads_with_facility()).get(
        "/api/v1/facilities/Z",
        params={"thread_id": "t1"},
    )
    assert response.status_code == 404


def test_another_threads_facility_is_404(app: FastAPI) -> None:
    response = _client(app, _threads_with_facility()).get(
        "/api/v1/facilities/A",
        params={"thread_id": "t2"},
    )
    assert response.status_code == 404


def test_a_thread_id_is_required_and_validated(app: FastAPI) -> None:
    client = _client(app, _threads_with_facility())
    assert client.get("/api/v1/facilities/A").status_code == 422
    assert client.get("/api/v1/facilities/A", params={"thread_id": "bad id!"}).status_code == 422


def test_an_odd_frs_id_is_rejected(app: FastAPI) -> None:
    client = _client(app, _threads_with_facility())
    assert client.get("/api/v1/facilities/a%20b", params={"thread_id": "t1"}).status_code == 422
