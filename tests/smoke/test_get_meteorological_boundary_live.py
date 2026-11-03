"""Live smoke test for get_meteorological_boundary against the Open-Meteo archive.

Run with ``uv run pytest -m smoke`` (needs network access; no API key). One request for one
year at a fixed point; the checks are on shape, units and plausibility, not on exact values.
"""

from __future__ import annotations

import pytest

from tools.exposure.meteorology import get_meteorological_boundary
from tools.schemas import Meteorology

pytestmark = pytest.mark.smoke

YEAR = 2022


@pytest.fixture(scope="module")
def conditions() -> Meteorology:
    return get_meteorological_boundary.invoke(
        {"latitude": 41.7, "longitude": -71.15, "reporting_year": YEAR},
    )


def test_real_data_not_the_default(conditions: Meteorology) -> None:
    assert conditions["source"] != "screening default", conditions["warnings"]
    assert str(YEAR) in conditions["source"]
    assert conditions["warnings"] == []


def test_values_are_plausible(conditions: Meteorology) -> None:
    assert 1.0 <= conditions["wind_speed"] <= 15.0  # m/s, annual mean at 10 m
    assert 0.0 <= conditions["wind_direction"] < 360.0
    assert conditions["stability_class"] in "ABCDEF"
    assert 250.0 <= conditions["ambient_temperature"] <= 310.0  # K


def test_new_england_wind_is_not_from_the_east(conditions: Meteorology) -> None:
    """A known climatology check on the direction convention: winds there are mostly westerly."""
    assert not 45.0 <= conditions["wind_direction"] <= 135.0


def test_future_year_returns_a_labelled_default() -> None:
    result = get_meteorological_boundary.invoke(
        {"latitude": 41.7, "longitude": -71.15, "reporting_year": 2999},
    )
    assert result["source"] == "screening default"
    assert "2999" in result["warnings"][0]
