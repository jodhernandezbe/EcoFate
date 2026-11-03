"""Tests for get_population_receptors (no network, no key: a mock Census service)."""

from __future__ import annotations

import math
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from config.population import load_population_settings
from tools.credentials import CENSUS_KEY
from tools.exposure import population
from tools.exposure.population import get_population_receptors

BASE = load_population_settings()
SETTINGS = replace(
    BASE,
    tract_url="https://tiger.test/query",
    acs_base_url="https://acs.test",
    acs_path="/data/{year}/profile",
    policy=replace(BASE.policy, delay_seconds=0.0, max_retries=0),
)
F, V = SETTINGS.fields, SETTINGS.variables
AREA = math.pi * 1609.0**2
HEADER = [V["total"], V["under_5"], V["under_18"], V["over_65"], "state", "county", "tract"]
FEATURE = {
    "attributes": {
        F["state"]: "99",
        F["county"]: "001",
        F["tract"]: "000100",
        F["land_area"]: 2 * AREA,
        F["latitude"]: "+41.5000000",
        F["longitude"]: "-071.2000000",
    },
}
ROW = ["1000", "100", "300", "200", "99", "001", "000100"]


@pytest.fixture
def requests_seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "tiger.test":
            return httpx.Response(200, json={"features": [FEATURE]})
        return httpx.Response(200, json=[HEADER, ROW])

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(population, "_open_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(population, "get_population_settings", lambda: SETTINGS)
    monkeypatch.setenv(SETTINGS.api_key_env_var, "fake-key-for-tests")  # pragma: allowlist secret
    return seen


def test_schema() -> None:
    tool = get_population_receptors
    assert tool.name == "get_population_receptors"
    assert set(tool.args) == {"latitude", "longitude", "radius_km"}
    assert tool.args["radius_km"].get("default", "missing") is None


def test_description_sets_expectations() -> None:
    description = " ".join(get_population_receptors.description.split())
    for text in (
        "residents",
        "percent of the total population",
        "ACS 5-year",
        "spread evenly",
        "query_emissions_inventory",
        "0.1 to 50",
        "screening default",
        "United States only",
        "calculate_exposure_metrics",
    ):
        assert text in description


def test_returns_census_estimates(requests_seen: list[httpx.Request]) -> None:
    result = get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    assert result["total_population"] == 500
    assert result["age_distribution"] == {"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0}
    assert result["source"].startswith("Census ACS")
    assert result["warnings"] == []
    assert len(requests_seen) == 2


def test_radius_argument_is_used(requests_seen: list[httpx.Request]) -> None:
    get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2, "radius_km": 3.0})
    assert requests_seen[0].url.params["distance"] == "3000.0"


def test_the_key_is_read_from_the_configured_variable(requests_seen: list[httpx.Request]) -> None:
    get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    assert requests_seen[1].url.params["key"] == "fake-key-for-tests"  # pragma: allowlist secret


def test_no_key_returns_the_default_without_a_request(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SETTINGS.api_key_env_var)
    result = get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    assert result["source"] == "screening default"
    assert SETTINGS.api_key_env_var in result["warnings"][0]
    assert requests_seen == []


def test_invalid_input_returns_the_default_without_a_request(
    requests_seen: list[httpx.Request],
) -> None:
    result = get_population_receptors.invoke(
        {"latitude": 41.5, "longitude": -71.2, "radius_km": 500.0},
    )
    assert result["source"] == "screening default"
    assert "radius" in result["warnings"][0]
    assert requests_seen == []


def test_the_request_key_is_preferred_over_the_environment(
    requests_seen: list[httpx.Request],
) -> None:
    with CENSUS_KEY.provide(SecretStr("turn-census-key")):  # pragma: allowlist secret
        get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    assert requests_seen[1].url.params["key"] == "turn-census-key"  # pragma: allowlist secret


def test_a_request_key_alone_is_enough(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SETTINGS.api_key_env_var)
    with CENSUS_KEY.provide(SecretStr("turn-census-key")):  # pragma: allowlist secret
        result = get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    assert result["source"] != "screening default"
    assert requests_seen[1].url.params["key"] == "turn-census-key"  # pragma: allowlist secret


def test_the_key_of_one_request_is_not_used_by_the_next(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SETTINGS.api_key_env_var)
    with CENSUS_KEY.provide(SecretStr("first-turn-key")):  # pragma: allowlist secret
        get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    seen_during_first = len(requests_seen)
    result = get_population_receptors.invoke({"latitude": 41.5, "longitude": -71.2})
    assert result["source"] == "screening default"  # no key left over from the first request
    assert len(requests_seen) == seen_during_first
