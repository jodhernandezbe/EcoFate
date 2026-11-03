"""Tests for tools.exposure.helpers.population.census (no network: an httpx mock transport).

State, county and tract codes and all counts are fake round numbers, not real census data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from config.population import load_population_settings
from tools.exposure.helpers.population.census import (
    CensusError,
    Counts,
    Tract,
    fetch_counts,
    fetch_tracts,
)
from tools.http import RetryingClient

BASE = load_population_settings()
SETTINGS = replace(
    BASE,
    tract_url="https://tiger.test/query",
    acs_base_url="https://acs.test",
    acs_path="/data/{year}/profile",
    acs_year=2000,
    policy=replace(BASE.policy, delay_seconds=0.0, max_retries=0),
)
F = SETTINGS.fields
V = SETTINGS.variables
KEY = "fake-key-for-tests"  # pragma: allowlist secret


class _Policy:
    delay_seconds = 0.0
    timeout_seconds = 5.0
    max_retries = 0
    backoff_seconds = 0.0


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> RetryingClient:
    return RetryingClient(_Policy(), httpx.Client(transport=httpx.MockTransport(handler)))


def _feature(
    state: object = "99",
    county: object = "001",
    tract: object = "000100",
    area: object = 1000,
) -> dict[str, object]:
    return {
        "attributes": {
            F["state"]: state,
            F["county"]: county,
            F["tract"]: tract,
            F["land_area"]: area,
        },
    }


def _tracts(
    body: object,
    status: int = 200,
) -> tuple[list[Tract] | CensusError, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    try:
        return fetch_tracts(41.5, -71.2, 1609.0, SETTINGS, _client(handler)), seen
    except CensusError as exc:
        return exc, seen


HEADER: list[object] = [
    V["total"],
    V["under_5"],
    V["under_18"],
    V["over_65"],
    "state",
    "county",
    "tract",
]


def _table(*rows: list[object]) -> list[list[object]]:
    return [HEADER, *rows]


def _counts(
    body: object | None,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Counts | None] | CensusError, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if body is None:
            return httpx.Response(status, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    try:
        return fetch_counts("99", "001", SETTINGS, _client(handler), KEY), seen
    except CensusError as exc:
        return exc, seen


def test_tract_request_parameters() -> None:
    _, seen = _tracts({"features": []})
    params = dict(seen[0].url.params)
    assert str(seen[0].url).startswith("https://tiger.test/query")
    assert params["geometry"] == "-71.2,41.5"
    assert params["distance"] == "1609.0"
    assert params["units"] == "esriSRUnit_Meter"
    assert params["returnGeometry"] == "false"
    assert set(params["outFields"].split(",")) == set(F.values())


def test_tracts_are_parsed_and_padded() -> None:
    result, _ = _tracts({"features": [_feature("9", "1", "100", 2500.5)]})
    assert result == [Tract("09", "001", "000100", 2500.5)]


def test_no_tract_is_a_valid_empty_answer() -> None:
    result, _ = _tracts({"features": []})
    assert result == []


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": 400}},
        {"features": "x"},
        {},
        [],
        "text",
        {"features": [{"no": "attributes"}]},
        {"features": [_feature(state="xx")]},
        {"features": [_feature(state=None)]},
        {"features": [_feature(county="12345")]},
        {"features": [_feature(tract=True)]},
        {"features": [_feature(area=None)]},
        {"features": [_feature(area=-5)]},
        {"features": [_feature(area="big")]},
        {"features": [5]},
    ],
)
def test_bad_tract_answers_are_errors(body: object) -> None:
    result, _ = _tracts(body)
    assert isinstance(result, CensusError)
    assert result.key_rejected is False


def test_a_truncated_tract_list_is_an_error() -> None:
    result, _ = _tracts({"features": [_feature()], "exceededTransferLimit": True})
    assert isinstance(result, CensusError)
    assert "incomplete" in str(result)


def test_a_tract_service_failure_is_an_error() -> None:
    result, _ = _tracts({"x": 1}, status=500)
    assert isinstance(result, CensusError)
    assert "census tract service could not be read" in str(result)


def test_counts_request_parameters_and_key() -> None:
    _, seen = _counts(_table(["1000", "50", "200", "150", "99", "001", "000100"]))
    params = dict(seen[0].url.params)
    assert str(seen[0].url).startswith("https://acs.test/data/2000/profile")
    assert params["for"] == "tract:*"
    assert params["in"] == "state:99 county:001"
    assert params["key"] == KEY
    assert params["get"] == ",".join(V[k] for k in ("total", "under_5", "under_18", "over_65"))


def test_counts_by_tract() -> None:
    result, _ = _counts(
        _table(
            ["1000", "50", "200", "150", "99", "001", "000100"],
            ["2000", "100", "400", "300", "99", "001", "000200"],
        ),
    )
    assert result == {
        "000100": Counts(1000.0, 50.0, 200.0, 150.0),
        "000200": Counts(2000.0, 100.0, 400.0, 300.0),
    }


def test_columns_are_found_by_name_not_position() -> None:
    header = ["tract", V["over_65"], V["under_18"], V["under_5"], V["total"]]
    result, _ = _counts([header, ["000100", "150", "200", "50", "1000"]])
    assert result == {"000100": Counts(1000.0, 50.0, 200.0, 150.0)}


@pytest.mark.parametrize("bad", [None, "-666666666", -666666666, "", "n/a", True, "nan"])
def test_unavailable_estimates_make_the_tract_unavailable(bad: object) -> None:
    for position in range(4):
        row: list[object] = ["1000", "50", "200", "150", "99", "001", "000100"]
        row[position] = bad
        result, _ = _counts(_table(row, ["1000", "50", "200", "150", "99", "001", "000200"]))
        assert isinstance(result, dict)
        assert result["000100"] is None
        assert result["000200"] == Counts(1000.0, 50.0, 200.0, 150.0)


def test_zero_is_a_real_estimate() -> None:
    result, _ = _counts(_table(["0", "0", "0", "0", "99", "001", "000100"]))
    assert result == {"000100": Counts(0.0, 0.0, 0.0, 0.0)}


def test_a_county_with_no_rows_is_empty() -> None:
    result, _ = _counts(None, status=204)
    assert result == {}


def test_a_table_with_only_a_header_is_empty() -> None:
    result, _ = _counts(_table())
    assert result == {}


@pytest.mark.parametrize(
    "body",
    [{"a": 1}, [], "text", [HEADER[:3], ["1", "2", "3"]], [["x"], ["1"]]],
)
def test_bad_acs_answers_are_errors(body: object) -> None:
    result, _ = _counts(body)
    assert isinstance(result, CensusError)
    assert result.key_rejected is False


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (302, {"Location": "https://acs.test/data/missing_key.html"}),
        (302, {"Location": "https://acs.test/data/invalid_key.html"}),
        (401, None),
        (403, None),
    ],
)
def test_a_refused_key_is_reported_and_not_retried(
    status: int,
    headers: dict[str, str] | None,
) -> None:
    result, seen = _counts(None, status=status, headers=headers)
    assert isinstance(result, CensusError)
    assert result.key_rejected is True
    assert "key" in str(result)
    assert KEY not in str(result)
    assert len(seen) == 1


def test_other_failures_are_not_key_problems_and_never_show_the_key() -> None:
    result, _ = _counts(None, status=400)
    assert isinstance(result, CensusError)
    assert result.key_rejected is False
    assert KEY not in str(result)
    assert "ACS data could not be read" in str(result)
