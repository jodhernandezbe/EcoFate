"""Keys in container mode come from the environment (no keychain); native mode ignores it."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from api import dependencies
from api.dependencies import AgentRuntime, get_runtime, key_variables
from api.main import create_app
from app.key_vault import default_service_keys
from config.ui import UiSettings
from tests.api.conftest import ORIGIN
from tests.api.streams import parse_sse
from tests.fakes import OPENAI_ENTRY, FakeCredentialStore, InMemoryThreadStore, scripted

OWN = {"Origin": ORIGIN}
KEY = "sk-proj-" + "c0N7a1N3r9" * 3  # pragma: allowlist secret


@pytest.fixture
def environment_key(monkeypatch: pytest.MonkeyPatch) -> str:
    variables = key_variables()
    monkeypatch.setenv(variables["openai"], KEY)
    monkeypatch.delenv(variables["census"], raising=False)
    monkeypatch.delenv(variables["comptox"], raising=False)
    return KEY


def _client(settings: UiSettings, *, container: bool, used: list[str]) -> Iterator[TestClient]:
    app = create_app(settings, keys_from_environment=container, threads=InMemoryThreadStore())
    model = scripted("an answer")

    def build(key: SecretStr) -> object:
        used.append(key.get_secret_value())
        return model

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(build, 10)  # pyright: ignore[reportArgumentType]
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def used() -> list[str]:
    return []


@pytest.fixture
def container(settings: UiSettings, environment_key: str, used: list[str]) -> Iterator[TestClient]:
    assert environment_key
    yield from _client(settings, container=True, used=used)


def test_container_status_reports_the_environment_key(container: TestClient) -> None:
    response = container.get("/api/v1/settings/keys")
    assert response.json() == {
        "openai": {"configured": True},
        "census": {"configured": False},
        "comptox": {"configured": False},
    }
    assert KEY not in response.text


def test_container_turn_uses_the_environment_key(container: TestClient, used: list[str]) -> None:
    response = container.post(
        "/api/v1/chat/stream",
        json={"thread_id": "t1", "message": "hello"},
        headers=OWN,
    )
    events = parse_sse(response.text)
    assert [e["type"] for e in events if e["type"] == "error"] == []
    assert used and set(used) == {KEY}
    assert KEY not in response.text


@pytest.mark.parametrize("method", ["post", "delete"])
def test_container_refuses_to_save_or_clear_a_key(container: TestClient, method: str) -> None:
    path = "/api/v1/settings/openai-key"
    if method == "post":
        response = container.post(path, json={"api_key": "sk-other" + "z" * 20}, headers=OWN)
    else:
        response = container.delete(path, headers=OWN)
    assert response.status_code == 503
    assert ".env" in response.json()["error"]
    assert KEY not in response.text


@pytest.mark.usefixtures("environment_key")
def test_native_mode_ignores_the_environment_key(
    settings: UiSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeCredentialStore()
    monkeypatch.setattr(dependencies, "default_service_keys", lambda: default_service_keys(store))
    native = create_app(settings, threads=InMemoryThreadStore())
    keys = dependencies.get_service_keys(cast(Request, SimpleNamespace(app=native)))
    assert keys.vault("openai").load() is None
    assert store.calls == [("get", *OPENAI_ENTRY)]


def test_container_mode_selects_the_environment_vaults(
    settings: UiSettings,
    environment_key: str,
) -> None:
    app = create_app(settings, keys_from_environment=True, threads=InMemoryThreadStore())
    keys = dependencies.get_service_keys(cast(Request, SimpleNamespace(app=app)))
    loaded = keys.vault("openai").load()
    assert loaded is not None
    assert loaded.get_secret_value() == environment_key
