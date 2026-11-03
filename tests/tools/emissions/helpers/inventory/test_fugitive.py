"""Tests for folding the fugitive air release into the stack records."""

from __future__ import annotations

import pytest

from config.loader import get_unit_settings
from tests.tools.emissions.records import emission_record
from tools.emissions.helpers.inventory.fugitive import fold_fugitive
from tools.schemas import EmissionRecord

ALIASES = get_unit_settings().aliases
FUGITIVE = "AIR FUG"


def _record(
    frs_id: str,
    medium: str,
    release: float,
    unit: str = "Pounds",
    year: int = 2020,
) -> EmissionRecord:
    base = emission_record(frs_id, 1.0)
    return {
        **base,
        "environmental_medium": medium,
        "total_release": release,
        "unit": unit,
        "reporting_year": year,
    }  # type: ignore[typeddict-item]


def test_both_media_give_the_stack_record_a_release_in_kilograms() -> None:
    folded = fold_fugitive(
        [_record("A", "AIR STACK", 100.0), _record("A", FUGITIVE, 1000.0, year=2019)],
        FUGITIVE,
        ALIASES,
    )
    assert len(folded) == 1 and folded[0]["environmental_medium"] == "AIR STACK"
    assert folded[0]["fugitive_release_kg_per_year"] == pytest.approx(1000 * 0.45359237)
    assert folded[0]["fugitive_reporting_year"] == 2019
    assert folded[0]["total_release"] == 100.0 and folded[0]["emission_rate"] == 1.0


def test_stack_only_has_no_fugitive_release() -> None:
    folded = fold_fugitive([_record("A", "AIR STACK", 100.0)], FUGITIVE, ALIASES)
    assert folded[0]["fugitive_release_kg_per_year"] is None
    assert folded[0]["fugitive_reporting_year"] is None


def test_fugitive_only_facility_is_not_a_stack_source() -> None:
    assert fold_fugitive([_record("B", FUGITIVE, 5.0)], FUGITIVE, ALIASES) == []


def test_a_reported_zero_stays_zero() -> None:
    folded = fold_fugitive(
        [_record("A", "AIR STACK", 1.0), _record("A", FUGITIVE, 0.0)],
        FUGITIVE,
        ALIASES,
    )
    assert folded[0]["fugitive_release_kg_per_year"] == 0.0


def test_unconvertible_unit_gives_none_not_a_guess() -> None:
    folded = fold_fugitive(
        [_record("A", "AIR STACK", 1.0), _record("A", FUGITIVE, 5.0, unit="Gallons")],
        FUGITIVE,
        ALIASES,
    )
    assert folded[0]["fugitive_release_kg_per_year"] is None
    assert folded[0]["fugitive_reporting_year"] is None


def test_other_facilities_are_not_mixed_up() -> None:
    folded = fold_fugitive(
        [
            _record("A", "AIR STACK", 1.0),
            _record("B", "AIR STACK", 1.0),
            _record("B", FUGITIVE, 10.0, unit="Grams"),
        ],
        FUGITIVE,
        ALIASES,
    )
    assert [r["fugitive_release_kg_per_year"] for r in folded] == [None, pytest.approx(0.01)]
