"""Live smoke test for get_population_receptors against Census TIGERweb and the ACS API.

Run with ``uv run pytest -m smoke`` (needs network access and the Census API key in ``.env``;
skipped without the key). The checks are on shape and plausibility, not on exact counts.
"""

from __future__ import annotations

import pytest

from tools.exposure.population import get_population_receptors
from tools.schemas import Population

pytestmark = [pytest.mark.smoke, pytest.mark.census]

BANDS = {"0-4", "5-17", "18-64", "65+"}


@pytest.fixture(scope="module")
def town() -> Population:
    """Residents within one mile of a point in Fall River, Massachusetts."""
    return get_population_receptors.invoke({"latitude": 41.70, "longitude": -71.15})


def test_real_census_data_not_the_default(town: Population) -> None:
    assert town["source"] != "screening default", town["warnings"]
    assert "Census ACS" in town["source"]


def test_counts_are_plausible(town: Population) -> None:
    assert 1_000 <= town["total_population"] <= 100_000  # one mile around a small city
    assert set(town["age_distribution"]) == BANDS
    assert sum(town["age_distribution"].values()) == pytest.approx(100.0, abs=0.05)
    assert all(0.0 <= share <= 100.0 for share in town["age_distribution"].values())


def test_a_bigger_circle_has_more_people() -> None:
    small = get_population_receptors.invoke(
        {"latitude": 41.70, "longitude": -71.15, "radius_km": 1.0},
    )
    large = get_population_receptors.invoke(
        {"latitude": 41.70, "longitude": -71.15, "radius_km": 4.0},
    )
    assert large["total_population"] > small["total_population"] > 0


def test_open_water_gets_the_labelled_default() -> None:
    result = get_population_receptors.invoke({"latitude": 27.0, "longitude": -90.0})
    assert result["source"] == "screening default"
    assert "no census tract" in result["warnings"][0]


def test_an_oversized_radius_is_refused_without_a_request() -> None:
    result = get_population_receptors.invoke(
        {"latitude": 41.70, "longitude": -71.15, "radius_km": 500.0},
    )
    assert result["source"] == "screening default"
    assert "radius" in result["warnings"][0]


def test_tracts_are_listed_nearest_first_within_the_circle(town: Population) -> None:
    tracts = town.get("tracts", [])
    assert tracts, town["warnings"]
    distances = [t["distance_m"] for t in tracts]
    assert distances == sorted(distances)
    assert all(0.0 <= t["bearing_deg"] < 360.0 and t["residents"] > 0 for t in tracts)
    assert all(set(t["age_distribution"]) == BANDS for t in tracts)
    assert all(len(t["geoid"]) == 11 for t in tracts)
