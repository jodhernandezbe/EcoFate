"""Tests for tools.exposure.helpers.meteorology.conditions (no network: an httpx mock transport)."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import httpx
import pytest

from config.meteorology import HOURLY_QUANTITIES, load_meteorology_settings
from tools.exposure.helpers.meteorology.conditions import (
    DEFAULT_SOURCE,
    input_problem,
    meteorology_for,
    screening_default,
)
from tools.http import RetryingClient
from tools.schemas import Meteorology

BASE = load_meteorology_settings()
SETTINGS = replace(BASE, policy=replace(BASE.policy, delay_seconds=0.0, backoff_seconds=0.0))
NAMES = SETTINGS.request.variables
TODAY = date(2001, 6, 1)
GOOD = {
    "temperature": 10.0,
    "wind_speed": 4.0,
    "wind_direction": 90.0,
    "solar_radiation": 0.0,
    "cloud_cover": 80.0,
    "low_cloud_cover": 0.0,
    "is_day": 0,
}


def _row(**changes: object) -> dict[str, object]:
    return {**GOOD, **changes}


def _payload(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "hourly": {NAMES[q]: [r[q] for r in rows] for q in HOURLY_QUANTITIES},
        "hourly_units": {NAMES[q]: SETTINGS.request.units[q] for q in HOURLY_QUANTITIES},
    }


class Run:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        http = httpx.Client(transport=httpx.MockTransport(handler))
        self.client = RetryingClient(SETTINGS.policy, http, lambda _s: None)

    def at(
        self,
        lat: float = 41.5,
        lon: float = -71.2,
        year: int | None = 2000,
        today: date = TODAY,
    ) -> Meteorology:
        return meteorology_for(lat, lon, year, SETTINGS, self.client, None, today)


def _ok(*rows: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=_payload(list(rows)))


def _is_default(result: Meteorology) -> bool:
    default = SETTINGS.screening_default
    return (
        result["source"] == DEFAULT_SOURCE
        and result["wind_speed"] == default.wind_speed
        and result["wind_direction"] == default.wind_direction
        and result["stability_class"] == default.stability_class
        and result["ambient_temperature"] == default.ambient_temperature
    )


def test_representative_conditions() -> None:
    result = Run(_ok(_row(), _row(wind_speed=6.0, temperature=20.0))).at()
    assert result["wind_speed"] == 5.0
    assert result["wind_direction"] == 90.0
    assert result["stability_class"] == "D"
    assert result["ambient_temperature"] == pytest.approx(288.15)
    assert result["source"] == f"Open-Meteo {SETTINGS.request.model} reanalysis 2000"
    assert result["warnings"] == []


def test_the_temperature_mean_is_converted_to_kelvin_once() -> None:
    result = Run(_ok(_row(temperature=-10.0), _row(temperature=10.0))).at()
    assert result["ambient_temperature"] == pytest.approx(273.15)


def test_calm_year_reports_the_minimum_with_a_warning() -> None:
    result = Run(_ok(_row(wind_speed=0.2), _row(wind_speed=0.4))).at()
    assert result["wind_speed"] == SETTINGS.summary.minimum_wind_speed
    assert "below the minimum" in result["warnings"][0]


def test_wind_from_the_north_wraps_around() -> None:
    rows = [_row(wind_direction=d) for d in (355.0, 358.0, 2.0, 5.0)]
    assert Run(_ok(*rows)).at()["wind_direction"] == 0.0


def test_modal_stability_class() -> None:
    rows = [_row(wind_speed=1.0)] * 2 + [_row(wind_speed=4.0)]  # cloudy night: F, F, D
    assert Run(_ok(*rows)).at()["stability_class"] == "F"


def test_default_year_is_used_when_none_is_given() -> None:
    run = Run(_ok(_row()))
    result = run.at(year=None, today=date(2030, 1, 1))
    assert str(SETTINGS.years.default_year) in result["source"]
    assert run.requests[0].url.params["start_date"] == f"{SETTINGS.years.default_year}-01-01"


def test_excluded_hours_are_counted_in_the_warnings() -> None:
    result = Run(_ok(_row(), _row(wind_speed=None), _row(cloud_cover=150.0), _row())).at()
    assert result["warnings"] == ["2 of 4 hours were left out: a value was missing or impossible"]


def test_missing_temperatures_only_affect_the_temperature_mean() -> None:
    result = Run(_ok(_row(temperature=None), _row(temperature=20.0))).at()
    assert result["ambient_temperature"] == pytest.approx(293.15)
    assert result["warnings"] == []


def test_no_temperature_at_all_uses_the_default_temperature() -> None:
    result = Run(_ok(_row(temperature=None), _row(temperature=None))).at()
    assert result["source"] != DEFAULT_SOURCE
    assert result["wind_speed"] == 4.0
    assert result["ambient_temperature"] == SETTINGS.screening_default.ambient_temperature
    assert "no temperature" in result["warnings"][0]


def test_no_usable_hour_gives_the_default() -> None:
    result = Run(_ok(_row(wind_speed=None), _row(wind_speed=-1.0))).at()
    assert _is_default(result)
    assert "no usable hourly data were found for 2000" in result["warnings"][0]
    assert "screening default" in result["warnings"][0]


def test_mismatched_series_give_the_default() -> None:
    payload = _payload([_row(), _row()])
    payload["hourly"][NAMES["temperature"]].pop()  # type: ignore[attr-defined]
    result = Run(httpx.Response(200, json=payload)).at()
    assert _is_default(result)
    assert "different lengths" in result["warnings"][0]


def test_unreachable_archive_gives_the_default_without_raising() -> None:
    attempts = SETTINGS.policy.max_retries + 1
    run = Run(*[httpx.ReadTimeout("slow")] * attempts)
    result = run.at()
    assert _is_default(result)
    assert "could not be read" in result["warnings"][0]
    assert len(run.requests) == attempts


def test_client_error_is_not_retried() -> None:
    run = Run(httpx.Response(400, json={"reason": "bad"}))
    result = run.at()
    assert _is_default(result)
    assert "400" in result["warnings"][0]
    assert len(run.requests) == 1


def test_throttled_then_success() -> None:
    run = Run(httpx.Response(429), _ok(_row()))
    assert run.at()["source"] != DEFAULT_SOURCE
    assert len(run.requests) == 2


@pytest.mark.parametrize(
    ("lat", "lon", "year", "fragment"),
    [
        (95.0, 0.0, 2000, "latitude 95.0"),
        (-90.1, 0.0, 2000, "latitude"),
        (math.nan, 0.0, 2000, "latitude"),
        (math.inf, 0.0, 2000, "latitude"),
        (True, 0.0, 2000, "latitude"),
        ("41.5", 0.0, 2000, "latitude"),
        (0.0, 181.0, 2000, "longitude 181.0"),
        (0.0, -180.5, 2000, "longitude"),
        (0.0, math.nan, 2000, "longitude"),
        (0.0, 0.0, 1939, "reporting year 1939"),
        (0.0, 0.0, 2001, "reporting year 2001"),
        (0.0, 0.0, True, "whole number"),
        (0.0, 0.0, "2000", "whole number"),
        (0.0, 0.0, 2000.5, "whole number"),
    ],
)
def test_invalid_input_makes_no_request(
    lat: object,
    lon: object,
    year: object,
    fragment: str,
) -> None:
    run = Run(_ok(_row()))
    result = meteorology_for(lat, lon, year, SETTINGS, run.client, None, TODAY)  # type: ignore[arg-type]
    assert _is_default(result)
    assert fragment in result["warnings"][0]
    assert run.requests == []


@pytest.mark.parametrize(("lat", "lon"), [(90.0, 180.0), (-90.0, -180.0), (0, 0)])
def test_boundary_coordinates_are_valid(lat: float, lon: float) -> None:
    assert input_problem(lat, lon, 2000, SETTINGS.years, TODAY) is None


@pytest.mark.parametrize(
    ("today", "year", "available"),
    [
        (date(2001, 1, 7), 2000, True),  # 7 days after the year ended: complete
        (date(2001, 1, 6), 2000, False),  # one day short
        (date(2001, 1, 6), 1999, True),
        (date(2000, 7, 1), 2000, False),  # the current year is never complete
        (date(2001, 6, 1), 1940, True),  # the first year
    ],
)
def test_year_window_follows_the_archive_lag(today: date, year: int, available: bool) -> None:
    problem = input_problem(0.0, 0.0, year, SETTINGS.years, today)
    assert (problem is None) is available


def test_screening_default_is_labelled() -> None:
    result = screening_default(SETTINGS, "why")
    assert result["source"] == DEFAULT_SOURCE
    assert result["warnings"] == ["why; using the screening default (generic, not site-specific)"]
