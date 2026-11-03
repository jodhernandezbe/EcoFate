"""Tests for the settings routes: the key never leaves the vault in plaintext."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.api.conftest import ORIGIN
from tests.fakes import CENSUS_ENTRY, COMPTOX_ENTRY, OPENAI_ENTRY, FakeCredentialStore

KEY = "sk-proj-" + "q9W8e7R6t5" * 3  # pragma: allowlist secret
OWN = {"Origin": ORIGIN}


def test_status_without_key(client: TestClient) -> None:
    response = client.get("/api/v1/settings/openai-key")
    assert response.json() == {"configured": False}


def test_save_then_status_shows_only_that_a_key_is_stored(
    client: TestClient,
    store: FakeCredentialStore,
) -> None:
    saved = client.post("/api/v1/settings/openai-key", json={"api_key": KEY}, headers=OWN)
    assert saved.status_code == 200
    assert saved.json() == {"configured": True}
    assert store.calls[-1][0] == "set"
    status = client.get("/api/v1/settings/openai-key")
    assert status.json()["configured"] is True
    assert KEY not in saved.text + status.text


def test_clear_removes_the_key(client: TestClient) -> None:
    client.post("/api/v1/settings/openai-key", json={"api_key": KEY}, headers=OWN)
    cleared = client.delete("/api/v1/settings/openai-key", headers=OWN)
    assert cleared.json() == {"configured": False}
    assert client.delete("/api/v1/settings/openai-key", headers=OWN).status_code == 200


@pytest.mark.parametrize("bad", ["", "   ", "sk-has space", "x" * 513])
def test_invalid_key_is_rejected_without_echo(client: TestClient, bad: str) -> None:
    response = client.post("/api/v1/settings/openai-key", json={"api_key": bad}, headers=OWN)
    assert response.status_code == 422
    assert bad.strip() == "" or bad not in response.text


def test_no_get_endpoint_returns_the_key(client: TestClient) -> None:
    client.post("/api/v1/settings/openai-key", json={"api_key": KEY}, headers=OWN)
    for path in ("/api/v1/settings/openai-key", "/api/v1/settings/client"):
        assert KEY not in client.get(path).text


def test_unavailable_keychain_is_a_safe_503(app: FastAPI, store: FakeCredentialStore) -> None:
    store.fail = True
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/settings/openai-key", json={"api_key": KEY}, headers=OWN)
    assert response.status_code == 503
    assert "keychain is unavailable" in response.json()["error"]
    assert KEY not in response.text


def test_client_config_comes_from_settings(client: TestClient) -> None:
    body = client.get("/api/v1/settings/client").json()
    assert body["thresholds"]["hq_concern"] == 1.0
    assert 3 <= len(body["suggestions"]) <= 4
    assert body["map"]["light_style"].startswith("https://")
    assert body["model"]


def test_client_config_carries_the_worker_tier_boundaries(client: TestClient) -> None:
    worker = client.get("/api/v1/settings/client").json()["worker_thresholds"]
    assert worker["ratio_exceedance"] == 1.0 and worker["ratio_elevated"] == 0.1
    assert worker["hq_elevated"] < worker["hq_exceedance"]
    assert worker["cancer_elevated"] < worker["cancer_exceedance"]


def test_client_config_carries_the_layout_limits(client: TestClient) -> None:
    layout = client.get("/api/v1/settings/client").json()["layout"]
    assert layout["rail"]["min_px"] < layout["rail"]["default_px"] <= layout["rail"]["max_px"]
    assert 0 < layout["chat"]["default_share"] <= layout["chat"]["max_share"] < 1
    assert layout["chat"]["min_px"] > 0
    assert 0 < layout["overview"]["min_share"] <= layout["overview"]["max_share"] < 1


# --- the three keys ---------------------------------------------------------------------------

ENTRIES = {"openai": OPENAI_ENTRY, "census": CENSUS_ENTRY, "comptox": COMPTOX_ENTRY}
PATHS = {
    "openai": "/api/v1/settings/openai-key",
    "census": "/api/v1/settings/census-key",
    "comptox": "/api/v1/settings/comptox-key",
}
SECRETS = {
    "openai": "sk-proj-" + "O1p2e3n4a5" * 3,  # pragma: allowlist secret
    "census": "c3n5u5k3y" + "7f" * 16,  # pragma: allowlist secret
    "comptox": "ct0x-" + "9d" * 14,  # pragma: allowlist secret
}


@pytest.mark.parametrize("name", list(PATHS))
def test_each_key_is_saved_under_its_own_keychain_entry(
    client: TestClient,
    store: FakeCredentialStore,
    name: str,
) -> None:
    response = client.post(PATHS[name], json={"api_key": SECRETS[name]}, headers=OWN)
    assert response.status_code == 200
    assert store.entries == {ENTRIES[name]: SECRETS[name]}
    assert response.json()["configured"] is True
    assert SECRETS[name] not in response.text


@pytest.mark.parametrize("name", list(PATHS))
def test_each_key_can_be_read_and_cleared(client: TestClient, name: str) -> None:
    assert client.get(PATHS[name]).json() == {"configured": False}
    client.post(PATHS[name], json={"api_key": SECRETS[name]}, headers=OWN)
    assert client.get(PATHS[name]).json()["configured"] is True
    cleared = client.delete(PATHS[name], headers=OWN)
    assert cleared.json() == {"configured": False}
    assert client.delete(PATHS[name], headers=OWN).status_code == 200  # clearing is idempotent


def test_saving_or_clearing_one_key_leaves_the_others(
    client: TestClient,
    store: FakeCredentialStore,
) -> None:
    for name, path in PATHS.items():
        client.post(path, json={"api_key": SECRETS[name]}, headers=OWN)
    client.delete(PATHS["census"], headers=OWN)
    assert store.entries == {
        OPENAI_ENTRY: SECRETS["openai"],
        COMPTOX_ENTRY: SECRETS["comptox"],
    }
    replacement = "sk-new-" + "N" * 20  # pragma: allowlist secret
    client.post(PATHS["openai"], json={"api_key": replacement}, headers=OWN)
    assert store.entries[OPENAI_ENTRY] == replacement
    assert store.entries[COMPTOX_ENTRY] == SECRETS["comptox"]


def test_the_combined_status_reports_every_key_without_revealing_any(
    client: TestClient,
) -> None:
    client.post(PATHS["openai"], json={"api_key": SECRETS["openai"]}, headers=OWN)
    client.post(PATHS["comptox"], json={"api_key": SECRETS["comptox"]}, headers=OWN)
    response = client.get("/api/v1/settings/keys")
    body = response.json()
    assert body["openai"]["configured"] is True
    assert body["census"] == {"configured": False}
    assert body["comptox"]["configured"] is True
    assert not any(secret in response.text for secret in SECRETS.values())


@pytest.mark.parametrize("name", list(PATHS))
@pytest.mark.parametrize("bad", ["", "   ", "has space", "tab\there", "x" * 513])
def test_each_key_is_validated_before_storing(
    client: TestClient,
    store: FakeCredentialStore,
    name: str,
    bad: str,
) -> None:
    response = client.post(PATHS[name], json={"api_key": bad}, headers=OWN)
    assert response.status_code == 422
    assert store.entries == {}
    assert bad.strip() == "" or bad not in response.text


@pytest.mark.parametrize("path", [*PATHS.values(), "/api/v1/settings/keys"])
def test_an_unavailable_keychain_is_a_safe_503_for_every_status(
    app: FastAPI,
    store: FakeCredentialStore,
    path: str,
) -> None:
    store.fail = True
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        response = client.get(path)
    assert response.status_code == 503
    assert "keychain is unavailable" in response.json()["error"]


@pytest.mark.parametrize("name", ["census", "comptox"])
def test_writes_to_the_service_keys_need_the_own_origin(client: TestClient, name: str) -> None:
    response = client.post(PATHS[name], json={"api_key": SECRETS[name]})
    assert response.status_code == 403


def test_the_map_starts_on_the_configured_view(client: TestClient) -> None:
    view = client.get("/api/v1/settings/client").json()["map"]["initial_view"]
    assert view["west"] < view["east"] and view["south"] < view["north"]
    assert -125.0 <= view["west"] and view["east"] <= -66.0  # the contiguous United States
