"""Tests for the liveness route: answers without any key, keychain, model or network call."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_runtime, get_service_keys
from api.services.agent_runner import AgentRuntime
from app.key_vault import default_service_keys
from config.ui import UiSettings
from tests.api.auth_support import build_app
from tests.api.conftest import ORIGIN
from tests.fakes import FakeCredentialStore, InMemoryThreadStore


def test_health_answers_ok_without_keys_or_model(
    app: FastAPI,
    client: TestClient,
    store: FakeCredentialStore,
) -> None:
    built: list[object] = []

    def factory(key: object) -> object:
        built.append(key)
        raise AssertionError("the health check must not build a chat model")

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(factory, 10)  # pyright: ignore[reportArgumentType]
    response = client.get("/api/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert built == []
    assert store.calls == []


def test_health_answers_when_the_keychain_is_unavailable(settings: UiSettings) -> None:
    failing = FakeCredentialStore(fail=True)
    api = build_app(settings, threads=InMemoryThreadStore())
    keys = default_service_keys(failing)
    api.dependency_overrides[get_service_keys] = lambda: keys
    with TestClient(api, base_url=ORIGIN) as client:
        assert client.get("/api/health").status_code == 200
    assert failing.calls == []


def test_health_refuses_a_foreign_host(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403


def test_container_bind_address_is_not_an_accepted_host(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": "0.0.0.0:8000"}).status_code == 403


async def _down() -> bool:
    return False


def test_health_is_503_unavailable_when_the_database_does_not_answer(settings: UiSettings) -> None:
    api = build_app(settings, threads=InMemoryThreadStore(), health_check=_down)
    with TestClient(api, base_url=ORIGIN) as client:
        response = client.get("/api/health")
    assert (response.status_code, response.json()) == (503, {"status": "unavailable"})
