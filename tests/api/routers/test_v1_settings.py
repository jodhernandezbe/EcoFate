"""Tests for the settings routes: a user's key is sealed per account and never returned."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.operator_keys import OperatorKeys
from tests.api.conftest import ORIGIN, signed_in
from tests.api.keys import OTHER_OWNER, OWNER
from tests.fakes import KeyBench

KEY = "sk-proj-" + "q9W8e7R6t5" * 3  # pragma: allowlist secret
OTHER_KEY = "sk-proj-" + "z9Y8x7W6v5" * 3  # pragma: allowlist secret
COMPTOX = "ct0x-" + "9d" * 14  # pragma: allowlist secret
OWN = {"Origin": ORIGIN}
PATH = "/api/v1/settings/openai-key"


@pytest.fixture
def store() -> KeyBench:
    """The installation provides a CompTox key and no Census key."""
    return KeyBench(OperatorKeys(comptox=SecretStr(COMPTOX)))


def test_status_without_key(client: TestClient) -> None:
    assert client.get(PATH).json() == {"configured": False}


def test_save_stores_only_ciphertext_for_that_user(client: TestClient, store: KeyBench) -> None:
    saved = client.post(PATH, json={"api_key": KEY}, headers=OWN)
    assert (saved.status_code, saved.json()) == (200, {"configured": True})
    assert list(store.rows.rows) == [(OWNER, "openai")]
    assert KEY.encode() not in store.rows.rows[(OWNER, "openai")].ciphertext
    assert client.get(PATH).json() == {"configured": True}
    assert KEY not in saved.text


def test_saving_twice_stores_a_different_ciphertext(client: TestClient, store: KeyBench) -> None:
    client.post(PATH, json={"api_key": KEY}, headers=OWN)
    first = store.rows.rows[(OWNER, "openai")]
    client.post(PATH, json={"api_key": KEY}, headers=OWN)
    second = store.rows.rows[(OWNER, "openai")]
    assert (first.nonce, first.ciphertext) != (second.nonce, second.ciphertext)


def test_replacing_a_key_keeps_one_row(client: TestClient, store: KeyBench) -> None:
    client.post(PATH, json={"api_key": KEY}, headers=OWN)
    client.post(PATH, json={"api_key": OTHER_KEY}, headers=OWN)
    assert len(store.rows.rows) == 1


def test_clear_deletes_the_row(client: TestClient, store: KeyBench) -> None:
    client.post(PATH, json={"api_key": KEY}, headers=OWN)
    cleared = client.delete(PATH, headers=OWN)
    assert cleared.json() == {"configured": False}
    assert store.rows.rows == {}
    assert client.delete(PATH, headers=OWN).status_code == 200  # clearing is idempotent


@pytest.mark.parametrize("bad", ["", "   ", "sk-has space", "tab\there", "x" * 513])
def test_invalid_key_is_rejected_without_echo_and_stores_nothing(
    client: TestClient,
    store: KeyBench,
    bad: str,
) -> None:
    response = client.post(PATH, json={"api_key": bad}, headers=OWN)
    assert response.status_code == 422
    assert bad.strip() == "" or bad not in response.text
    assert store.rows.rows == {}


def test_another_users_status_is_not_configured(app: FastAPI, store: KeyBench) -> None:
    store.give(KEY, OWNER)
    with (
        signed_in(app, email="a@example.com") as ana,
        signed_in(app, email="b@example.com") as bo,
    ):
        assert ana.get(PATH).json() == {"configured": True}
        assert bo.get(PATH).json() == {"configured": False}
        assert bo.get("/api/v1/settings/keys").json()["openai"] == {"configured": False}


def test_one_users_save_and_clear_never_touch_another(app: FastAPI, store: KeyBench) -> None:
    store.give(KEY, OWNER)
    store.give(OTHER_KEY, OTHER_OWNER)
    with (
        signed_in(app, email="a@example.com") as ana,
        signed_in(app, email="b@example.com") as bo,
    ):
        bo.delete(PATH, headers=OWN)
        assert ana.get(PATH).json() == {"configured": True}
        bo.post(PATH, json={"api_key": KEY}, headers=OWN)
    assert (OWNER, "openai") in store.rows.rows
    assert (OTHER_OWNER, "openai") in store.rows.rows


def test_a_ciphertext_copied_to_another_user_reads_as_not_configured(
    app: FastAPI,
    store: KeyBench,
) -> None:
    store.give(KEY, OWNER)
    from dataclasses import replace

    store.rows.rows[(OTHER_OWNER, "openai")] = replace(
        store.rows.rows[(OWNER, "openai")],
        user_id=OTHER_OWNER,
    )
    with signed_in(app, email="a@example.com"), signed_in(app, email="b@example.com") as bo:
        assert bo.get(PATH).json() == {"configured": False}


@pytest.mark.parametrize("name", ["census-key", "comptox-key"])
@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_the_operator_key_routes_are_gone(
    client: TestClient,
    store: KeyBench,
    name: str,
    method: str,
) -> None:
    body = {"api_key": KEY} if method == "post" else None
    response = client.request(method, f"/api/v1/settings/{name}", json=body, headers=OWN)
    assert response.status_code == 404
    assert store.rows.rows == {}


def test_the_combined_status_reports_the_users_key_and_the_services(
    client: TestClient,
) -> None:
    client.post(PATH, json={"api_key": KEY}, headers=OWN)
    response = client.get("/api/v1/settings/keys")
    assert response.json() == {
        "openai": {"configured": True},
        "services": {"census": {"available": False}, "comptox": {"available": True}},
    }
    assert KEY not in response.text and COMPTOX not in response.text


def test_the_combined_status_with_no_keys_at_all(app: FastAPI, store: KeyBench) -> None:
    quiet = KeyBench()
    app.state.keys = quiet.services
    with signed_in(app, email="solo@example.com") as client:
        assert client.get("/api/v1/settings/keys").json() == {
            "openai": {"configured": False},
            "services": {"census": {"available": False}, "comptox": {"available": False}},
        }


def _walk_gets(client: TestClient) -> list[Any]:
    paths = ["/api/v1/settings/openai-key", "/api/v1/settings/keys", "/api/v1/settings/client"]
    return [client.get(path) for path in paths]


def test_no_get_endpoint_returns_a_key(client: TestClient) -> None:
    client.post(PATH, json={"api_key": KEY}, headers=OWN)
    for response in _walk_gets(client):
        assert KEY not in response.text
        assert COMPTOX not in response.text


def test_writes_need_the_own_origin(client: TestClient) -> None:
    assert client.post(PATH, json={"api_key": KEY}).status_code == 403
    assert client.delete(PATH).status_code == 403


def test_a_provider_failure_message_carries_no_key(client: TestClient) -> None:
    response = client.post(PATH, json={"api_key": "x" * 513}, headers=OWN)
    assert KEY not in response.text and "x" * 20 not in response.text


def test_client_config_comes_from_settings(client: TestClient) -> None:
    body = client.get("/api/v1/settings/client").json()
    assert body["bands"]["hq_upper"] == 1.0
    assert "thresholds" not in body and "worker_thresholds" not in body
    assert 3 <= len(body["suggestions"]) <= 4
    assert body["map"]["light_style"].startswith("https://")
    assert body["model"]


def test_client_config_carries_the_band_boundaries_of_both_pathways(client: TestClient) -> None:
    bands = client.get("/api/v1/settings/client").json()["bands"]
    assert set(bands) == {
        "hq_lower",
        "hq_upper",
        "cancer_risk_lower",
        "cancer_risk_upper",
        "oel_ratio_lower",
        "oel_ratio_upper",
    }
    for quantity in ("hq", "cancer_risk", "oel_ratio"):
        assert 0 < bands[f"{quantity}_lower"] < bands[f"{quantity}_upper"]
    assert bands["oel_ratio_lower"] == 0.1 and bands["oel_ratio_upper"] == 1.0


def test_client_config_carries_the_layout_limits(client: TestClient) -> None:
    layout = client.get("/api/v1/settings/client").json()["layout"]
    assert layout["rail"]["min_px"] < layout["rail"]["default_px"] <= layout["rail"]["max_px"]
    assert 0 < layout["chat"]["default_share"] <= layout["chat"]["max_share"] < 1
    assert layout["chat"]["min_px"] > 0
    assert 0 < layout["overview"]["min_share"] <= layout["overview"]["max_share"] < 1


def test_the_map_starts_on_the_configured_view(client: TestClient) -> None:
    view = client.get("/api/v1/settings/client").json()["map"]["initial_view"]
    assert view["west"] < view["east"] and view["south"] < view["north"]
    assert -125.0 <= view["west"] and view["east"] <= -66.0  # the contiguous United States
