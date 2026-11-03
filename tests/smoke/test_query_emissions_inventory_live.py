"""Live smoke test for query_emissions_inventory against EPA Envirofacts.

Run with ``uv run pytest -m smoke`` (needs network access; no API key). Formaldehyde is
widely reported, so the page cap is lowered to keep the run short (about 30 s); the checks
are on the shape and plausibility of what comes back, not on totals, which change yearly.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from config.loader import load_tri_settings
from tools.emissions import inventory
from tools.emissions.inventory import query_emissions_inventory
from tools.schemas import EmissionRecord

pytestmark = pytest.mark.smoke

EAST = {"GU", "MP"}
G_PER_LB = 453.59237


@pytest.fixture(scope="module")
def records() -> list[EmissionRecord]:
    settings = replace(load_tri_settings(), max_pages=2)
    patch = pytest.MonkeyPatch()
    patch.setattr(inventory, "get_tri_settings", lambda: settings)
    try:
        call = {"type": "tool_call", "id": "c1", "name": "query_emissions_inventory"}
        return query_emissions_inventory.invoke(
            {**call, "args": {"cas_number": "50-00-0"}},
        ).artifact
    finally:
        patch.undo()


def test_returns_facilities(records: list[EmissionRecord]) -> None:
    assert len(records) > 100


def test_one_record_per_facility_and_medium(records: list[EmissionRecord]) -> None:
    keys = [(r["environmental_medium"], r["frs_id"]) for r in records]
    assert len(keys) == len(set(keys))
    assert {r["environmental_medium"] for r in records} == {"AIR STACK"}


def test_identity_year_and_unit(records: list[EmissionRecord]) -> None:
    for r in records:
        assert r["frs_id"].isdigit()
        assert 1987 <= r["reporting_year"] <= 2100
        assert r["unit"] == "Pounds"


def test_quantities_and_rates_are_consistent(records: list[EmissionRecord]) -> None:
    for r in records:
        assert math.isfinite(r["total_release"]) and r["total_release"] >= 0
        expected = r["total_release"] * G_PER_LB / (r["operating_hours_per_year"] * 3600)
        assert r["emission_rate"] == pytest.approx(expected)


def test_coordinates_are_in_the_expected_hemisphere(records: list[EmissionRecord]) -> None:
    for r in records:
        assert 0 < r["latitude"] < 75
        if r["state"] in EAST:
            assert r["longitude"] > 0
        else:
            assert -180 < r["longitude"] < -60


def test_fugitive_release_is_folded_into_facilities(records: list[EmissionRecord]) -> None:
    folded = [
        (r["fugitive_release_kg_per_year"], r["fugitive_reporting_year"])
        for r in records
        if r["fugitive_release_kg_per_year"] is not None
    ]
    assert len(folded) > 100
    assert all(kilograms >= 0.0 and year is not None for kilograms, year in folded)
