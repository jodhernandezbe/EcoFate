"""Tests for tools.exposure.helpers.population.receptors (no network: a mock Census service).

Codes and counts are fake round numbers, not real census data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import httpx
import pytest

from config.population import load_population_settings
from tools.exposure.helpers.population.receptors import (
    DEFAULT_SOURCE,
    population_around,
    screening_default,
)
from tools.http import RetryingClient
from tools.schemas import Population

BASE = load_population_settings()
SETTINGS = replace(
    BASE,
    tract_url="https://tiger.test/query",
    acs_base_url="https://acs.test",
    acs_path="/data/{year}/profile",
    acs_year=2000,
    default_radius_km=1.0,
    min_radius_km=0.5,
    max_radius_km=5.0,
    max_counties=2,
    policy=replace(BASE.policy, delay_seconds=0.0, max_retries=0),
)
F, V = SETTINGS.fields, SETTINGS.variables
KEY = "fake-key-for-tests"  # pragma: allowlist secret
CIRCLE_1KM_M2 = math.pi * 1000.0**2
HEADER = [V["total"], V["under_5"], V["under_18"], V["over_65"], "state", "county", "tract"]


class _Policy:
    delay_seconds = 0.0
    timeout_seconds = 5.0
    max_retries = 0
    backoff_seconds = 0.0


def _tract(
    county: str = "001",
    tract: str = "000100",
    area: float = CIRCLE_1KM_M2,
    point: tuple[object, object] | None = ("+41.5000000", "-071.2000000"),
) -> dict[str, object]:
    attributes: dict[str, object] = {
        F["state"]: "99",
        F["county"]: county,
        F["tract"]: tract,
        F["land_area"]: area,
    }
    if point is not None:
        attributes[F["latitude"]], attributes[F["longitude"]] = point
    return {"attributes": attributes}


def _row(
    total: object,
    under_5: object,
    under_18: object,
    over_65: object,
    county: str = "001",
    tract: str = "000100",
) -> list[object]:
    return [total, under_5, under_18, over_65, "99", county, tract]


@dataclass
class Service:
    """A mock Census service: tract features, ACS tables per county, and request logs."""

    features: list[dict[str, object]] = field(default_factory=lambda: [])
    tables: dict[str, list[list[object]]] = field(default_factory=lambda: {})
    acs_status: int | None = None
    tract_failure: Exception | None = None
    truncated: bool = False
    tract_requests: list[httpx.Request] = field(default_factory=lambda: [])
    acs_requests: list[httpx.Request] = field(default_factory=lambda: [])

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "tiger.test":
            self.tract_requests.append(request)
            if self.tract_failure is not None:
                raise self.tract_failure
            body: dict[str, object] = {"features": self.features}
            if self.truncated:
                body["exceededTransferLimit"] = True
            return httpx.Response(200, json=body)
        self.acs_requests.append(request)
        if self.acs_status is not None:
            return httpx.Response(self.acs_status)
        county = request.url.params["in"].split("county:")[1]
        return httpx.Response(200, json=[HEADER, *self.tables.get(county, [])])

    def at(
        self,
        lat: object = 41.5,
        lon: object = -71.2,
        radius: object = 1.0,
        key: str = KEY,
        settings: object = SETTINGS,
    ) -> Population:
        client = RetryingClient(_Policy(), httpx.Client(transport=httpx.MockTransport(self.handle)))
        return population_around(lat, lon, radius, settings, client, key)  # type: ignore[arg-type]


def _is_default(result: Population) -> bool:
    return result["source"] == DEFAULT_SOURCE


def test_half_covered_halves_the_count() -> None:
    service = Service(
        [_tract(area=2 * CIRCLE_1KM_M2)],
        {"001": [_row("1000", "100", "300", "200")]},
    )
    result = service.at()
    assert result["total_population"] == 500
    assert result["age_distribution"] == {"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0}
    assert result["source"] == "Census ACS 2000 5-year (DP05), 1 tracts"
    assert result["warnings"] == []


def test_circle_larger_than_the_tracts_returns_all_of_them() -> None:
    service = Service(
        [_tract(area=CIRCLE_1KM_M2 / 4)],
        {"001": [_row("1000", "100", "300", "200")]},
    )
    assert service.at()["total_population"] == 1000


def test_counties_are_combined() -> None:
    service = Service(
        [_tract("001", "000100"), _tract("002", "000200")],
        {
            "001": [_row("600", "60", "180", "120", "001", "000100")],
            "002": [_row("400", "40", "120", "80", "002", "000200")],
        },
    )
    result = service.at()
    assert result["total_population"] == 500  # 1,000 residents, circle = half the land
    assert len(service.acs_requests) == 2
    assert result["age_distribution"] == {"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0}


def test_only_the_intersecting_tracts_of_a_county_are_counted() -> None:
    service = Service(
        [_tract(tract="000100")],
        {
            "001": [
                _row("100", "10", "30", "20", tract="000100"),
                _row("900", "90", "270", "180", tract="000999"),
            ],
        },
    )
    assert service.at()["total_population"] == 100


def test_default_radius_is_used_when_none_is_given() -> None:
    service = Service(
        [_tract(area=2 * CIRCLE_1KM_M2)],
        {"001": [_row("1000", "100", "300", "200")]},
    )
    result = service.at(radius=None)
    assert result["total_population"] == 500
    assert service.tract_requests[0].url.params["distance"] == "1000.0"


def test_request_parameters() -> None:
    service = Service([_tract()], {"001": [_row("10", "1", "3", "2")]})
    service.at(lat=41.5, lon=-71.2, radius=2.0)
    assert service.tract_requests[0].url.params["geometry"] == "-71.2,41.5"
    assert service.tract_requests[0].url.params["distance"] == "2000.0"
    assert service.acs_requests[0].url.params["key"] == KEY


def test_tracts_with_no_residents() -> None:
    service = Service([_tract()], {"001": [_row("0", "0", "0", "0")]})
    result = service.at()
    assert result["total_population"] == 0
    assert result["age_distribution"] == {"0-4": 0.0, "5-17": 0.0, "18-64": 0.0, "65+": 0.0}
    assert not _is_default(result)
    assert result["warnings"] == ["the tracts report no residents"]


def test_a_tract_without_an_estimate_is_left_out_and_reported() -> None:
    service = Service(
        [_tract(tract="000100"), _tract(tract="000200")],
        {
            "001": [
                _row("-666666666", "1", "3", "2", tract="000100"),
                _row("1000", "100", "300", "200", tract="000200"),
            ],
        },
    )
    result = service.at()
    assert result["total_population"] == 1000
    assert result["warnings"] == ["1 of 2 tracts had no usable estimate and were left out"]


def test_a_tract_missing_from_the_acs_table_is_left_out() -> None:
    service = Service(
        [_tract(tract="000100"), _tract(tract="000200")],
        {"001": [_row("1000", "100", "300", "200", tract="000200")]},
    )
    assert "1 of 2 tracts" in service.at()["warnings"][0]


def test_no_tract_with_data_gives_the_default() -> None:
    service = Service([_tract()], {"001": [_row(None, "1", "3", "2")]})
    result = service.at()
    assert _is_default(result)
    assert "no intersecting tract had usable estimates" in result["warnings"][0]


def test_inconsistent_counts_give_the_default() -> None:
    service = Service([_tract()], {"001": [_row("1000", "400", "300", "200")]})
    result = service.at()
    assert _is_default(result)
    assert "inconsistent" in result["warnings"][0]


def test_open_water_gives_the_default_not_zero() -> None:
    result = Service([]).at()
    assert _is_default(result)
    assert "no census tract was found" in result["warnings"][0]
    assert result["total_population"] > 0


def test_the_default_scales_with_the_circle() -> None:
    result = Service([]).at(radius=2.0)
    density = SETTINGS.screening_default.residents_per_km2
    assert result["total_population"] == round(density * math.pi * 4.0)
    assert result["age_distribution"] == dict(SETTINGS.screening_default.age_distribution)
    assert "screening default" in result["warnings"][0]


def test_truncated_tract_list_gives_the_default() -> None:
    result = Service([_tract()], truncated=True).at()
    assert _is_default(result)
    assert "incomplete" in result["warnings"][0]


def test_unreachable_tract_service_gives_the_default_without_raising() -> None:
    service = Service(tract_failure=httpx.ReadTimeout("slow"))
    result = service.at()
    assert _is_default(result)
    assert "could not be read" in result["warnings"][0]
    assert service.acs_requests == []


@pytest.mark.parametrize("key", ["", "   "])
def test_no_key_makes_no_request_and_names_the_variable(key: str) -> None:
    service = Service([_tract()], {"001": [_row("10", "1", "3", "2")]})
    result = service.at(key=key)
    assert _is_default(result)
    assert SETTINGS.api_key_env_var in result["warnings"][0]
    assert service.acs_requests == [] and service.tract_requests == []


@pytest.mark.parametrize("status", [302, 401, 403])
def test_a_refused_key_gives_the_default_and_is_not_retried(status: int) -> None:
    service = Service([_tract()], acs_status=status)
    result = service.at()
    assert _is_default(result)
    assert "key is missing or was rejected" in result["warnings"][0]
    assert len(service.acs_requests) == 1
    assert KEY not in repr(result)


def test_the_key_never_appears_in_any_result() -> None:
    service = Service([_tract()], {"001": [_row("1000", "100", "300", "200")]})
    assert KEY not in repr(service.at())
    assert KEY not in repr(Service([_tract()], acs_status=400).at())


def test_too_many_counties_make_no_acs_request() -> None:
    service = Service([_tract("001"), _tract("002"), _tract("003")])
    result = service.at()
    assert _is_default(result)
    assert "3 counties, above the limit of 2" in result["warnings"][0]
    assert service.acs_requests == []


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"lat": 95.0}, "latitude 95.0"),
        ({"lat": math.nan}, "latitude"),
        ({"lat": True}, "latitude"),
        ({"lon": -181.0}, "longitude"),
        ({"radius": 6.0}, "radius 6.0 km is invalid"),
        ({"radius": 0.0}, "radius 0.0"),
        ({"radius": -1.0}, "radius"),
        ({"radius": 0.4}, "radius"),
        ({"radius": math.inf}, "radius"),
        ({"radius": True}, "radius"),
        ({"radius": "2"}, "radius"),
    ],
)
def test_invalid_input_makes_no_request(kwargs: dict[str, object], fragment: str) -> None:
    service = Service([_tract()], {"001": [_row("10", "1", "3", "2")]})
    result = service.at(**kwargs)  # type: ignore[arg-type]
    assert _is_default(result)
    assert fragment in result["warnings"][0]
    assert service.tract_requests == [] and service.acs_requests == []


def test_the_radius_message_names_the_limits() -> None:
    warning = Service().at(radius=6.0)["warnings"][0]
    assert "0.5" in warning and "5" in warning


@pytest.mark.parametrize("radius", [0.5, 5.0])
def test_radius_limits_are_inclusive(radius: float) -> None:
    service = Service([_tract(area=1e12)], {"001": [_row("10", "1", "3", "2")]})
    assert not _is_default(service.at(radius=radius))


def test_screening_default_is_labelled() -> None:
    result = screening_default(SETTINGS, 1.0, "why")
    assert result["source"] == DEFAULT_SOURCE
    assert result["warnings"] == ["why; using the screening default (generic, not site-specific)"]


def _two_tracts(near: tuple[object, object], far: tuple[object, object]) -> Service:
    return Service(
        [_tract(tract="000100", point=far), _tract(tract="000200", point=near)],
        {
            "001": [
                _row("1000", "100", "300", "200", tract="000100"),
                _row("500", "50", "150", "100", tract="000200"),
            ],
        },
    )


def test_tracts_are_listed_nearest_first_with_distance_and_bearing() -> None:
    result = _two_tracts(("+41.5000000", "-071.1900000"), ("+41.5500000", "-071.2000000")).at()
    tracts = result.get("tracts", [])
    assert [t["geoid"] for t in tracts] == ["99001000200", "99001000100"]
    east, north = tracts
    assert east["bearing_deg"] == pytest.approx(90.0, abs=0.1)
    assert north["bearing_deg"] == pytest.approx(0.0, abs=0.1)
    assert 0.0 < east["distance_m"] < north["distance_m"]
    assert (east["residents"], north["residents"]) == (500, 1000)
    assert east["age_distribution"] == {"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0}
    assert east["land_area_km2"] == pytest.approx(CIRCLE_1KM_M2 / 1e6)
    assert (east["latitude"], east["longitude"]) == (41.5, -71.19)


def test_the_pooled_result_does_not_change_when_tracts_are_listed() -> None:
    result = _two_tracts(("+41.5", "-71.19"), ("+41.55", "-71.2")).at()
    assert result["total_population"] == 750
    assert result["warnings"] == []


def test_a_tract_without_a_point_is_counted_but_not_listed() -> None:
    result = _two_tracts(("+41.5", "-71.19"), ("not a number", "-71.2")).at()
    assert result["total_population"] == 750
    assert [t["geoid"] for t in result.get("tracts", [])] == ["99001000200"]
    assert result["warnings"] == [
        "1 tracts have no internal point and are not listed with a distance",
    ]


def test_a_point_outside_the_globe_is_not_used() -> None:
    result = _two_tracts(("+41.5", "-71.19"), ("+95.0", "-71.2")).at()
    assert [t["geoid"] for t in result.get("tracts", [])] == ["99001000200"]


def test_the_listing_is_capped_and_says_how_many_were_not_listed() -> None:
    capped = replace(SETTINGS, max_tracts_listed=1)
    service = _two_tracts(("+41.5", "-71.19"), ("+41.55", "-71.2"))
    result = service.at(settings=capped)
    assert [t["geoid"] for t in result.get("tracts", [])] == ["99001000200"]
    assert result.get("tracts_not_listed") == 1
    assert result["total_population"] == 750


def test_a_tract_without_residents_is_not_listed() -> None:
    service = Service([_tract()], {"001": [_row("0", "0", "0", "0")]})
    assert service.at().get("tracts") == []


def test_the_screening_default_lists_no_tracts() -> None:
    result = Service().at(key="")
    assert _is_default(result)
    assert (result.get("tracts", []), result.get("tracts_not_listed")) == ([], 0)
