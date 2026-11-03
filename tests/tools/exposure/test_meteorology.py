"""Tests for get_meteorological_boundary (no network: an httpx mock transport)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import httpx
import pytest

from config.meteorology import HOURLY_QUANTITIES, load_meteorology_settings
from tools.exposure import meteorology
from tools.exposure.meteorology import get_meteorological_boundary

BASE = load_meteorology_settings()
SETTINGS = replace(BASE, policy=replace(BASE.policy, delay_seconds=0.0, backoff_seconds=0.0))
NAMES = SETTINGS.request.variables
ROW = {
    "temperature": 10.0,
    "wind_speed": 4.0,
    "wind_direction": 90.0,
    "solar_radiation": 0.0,
    "cloud_cover": 80.0,
    "low_cloud_cover": 0.0,
    "is_day": 0,
}


@pytest.fixture
def requests_seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    body = {
        "hourly": {NAMES[q]: [ROW[q]] * 3 for q in HOURLY_QUANTITIES},
        "hourly_units": {NAMES[q]: SETTINGS.request.units[q] for q in HOURLY_QUANTITIES},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(meteorology, "_open_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(meteorology, "get_meteorology_settings", lambda: SETTINGS)
    monkeypatch.setattr(meteorology, "_today", lambda: date(2030, 6, 1))
    return seen


def test_schema() -> None:
    tool = get_meteorological_boundary
    assert tool.name == "get_meteorological_boundary"
    assert set(tool.args) == {"latitude", "longitude", "reporting_year"}
    assert tool.args["reporting_year"].get("default", "missing") is None


def test_description_sets_expectations() -> None:
    description = " ".join(get_meteorological_boundary.description.split())
    for text in (
        "m/s",
        "degrees clockwise from north",
        "K, annual mean",
        "annual representatives, not worst-case",
        "about 25 km",
        "query_emissions_inventory",
        "screening default",
        "10 m",
    ):
        assert text in description


def test_returns_conditions(requests_seen: list[httpx.Request]) -> None:
    result = get_meteorological_boundary.invoke({"latitude": 41.5, "longitude": -71.2})
    assert result["wind_speed"] == 4.0
    assert result["stability_class"] == "D"
    assert result["ambient_temperature"] == pytest.approx(283.15)
    assert result["source"].endswith(str(SETTINGS.years.default_year))
    assert len(requests_seen) == 1


def test_year_argument_is_used(requests_seen: list[httpx.Request]) -> None:
    result = get_meteorological_boundary.invoke(
        {"latitude": 41.5, "longitude": -71.2, "reporting_year": 2010},
    )
    assert result["source"].endswith("2010")
    assert requests_seen[0].url.params["start_date"] == "2010-01-01"


def test_invalid_input_returns_the_default_without_a_request(
    requests_seen: list[httpx.Request],
) -> None:
    result = get_meteorological_boundary.invoke({"latitude": 95.0, "longitude": 0.0})
    assert result["source"] == "screening default"
    assert "latitude" in result["warnings"][0]
    assert requests_seen == []
