"""Tests for folding the fugitive air release into the stack records."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest

from config.loader import get_unit_settings
from tests.tools.emissions.records import emission_record
from tools.emissions.helpers.inventory.fugitive import fold_fugitive
from tools.schemas import EmissionRecord, FacilityRecord

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
    folded = _stack(
        [_record("A", "AIR STACK", 100.0), _record("A", FUGITIVE, 1000.0, year=2019)],
        FUGITIVE,
        ALIASES,
    )
    assert len(folded) == 1 and folded[0]["environmental_medium"] == "AIR STACK"
    assert folded[0]["fugitive_release_kg_per_year"] == pytest.approx(1000 * 0.45359237)
    assert folded[0]["fugitive_reporting_year"] == 2019
    assert folded[0]["total_release"] == 100.0 and folded[0]["emission_rate"] == 1.0


def test_stack_only_has_no_fugitive_release() -> None:
    folded = _stack([_record("A", "AIR STACK", 100.0)], FUGITIVE, ALIASES)
    assert folded[0]["fugitive_release_kg_per_year"] is None
    assert folded[0]["fugitive_reporting_year"] is None


def _stack(
    records: list[EmissionRecord],
    medium: str,
    aliases: Mapping[str, str],
) -> list[EmissionRecord]:
    return fold_fugitive(records, medium, aliases).stack


def test_a_reported_zero_stays_zero() -> None:
    folded = _stack(
        [_record("A", "AIR STACK", 1.0), _record("A", FUGITIVE, 0.0)],
        FUGITIVE,
        ALIASES,
    )
    assert folded[0]["fugitive_release_kg_per_year"] == 0.0


def test_unconvertible_unit_gives_none_not_a_guess() -> None:
    folded = _stack(
        [_record("A", "AIR STACK", 1.0), _record("A", FUGITIVE, 5.0, unit="Gallons")],
        FUGITIVE,
        ALIASES,
    )
    assert folded[0]["fugitive_release_kg_per_year"] is None
    assert folded[0]["fugitive_reporting_year"] is None


def test_other_facilities_are_not_mixed_up() -> None:
    folded = _stack(
        [
            _record("A", "AIR STACK", 1.0),
            _record("B", "AIR STACK", 1.0),
            _record("B", FUGITIVE, 10.0, unit="Grams"),
        ],
        FUGITIVE,
        ALIASES,
    )
    assert [r["fugitive_release_kg_per_year"] for r in folded] == [None, pytest.approx(0.01)]


def test_fugitive_only_facility_is_worker_only_and_not_a_stack_source() -> None:
    found = fold_fugitive([_record("B", FUGITIVE, 5.0, year=2019)], FUGITIVE, ALIASES)
    assert found.stack == []
    (only,) = found.worker_only
    assert only["frs_id"] == "B"
    assert only["fugitive_release_kg_per_year"] == pytest.approx(5 * 0.45359237)
    assert only["fugitive_reporting_year"] == 2019


def test_a_worker_only_facility_has_no_stack_release_or_emission_rate() -> None:
    (only,) = fold_fugitive([_record("B", FUGITIVE, 5.0)], FUGITIVE, ALIASES).worker_only
    assert set(only) == set(FacilityRecord.__annotations__)
    for stack_field in ("emission_rate", "total_release", "unit", "environmental_medium"):
        assert stack_field not in only


def test_a_facility_with_a_stack_release_is_never_worker_only() -> None:
    both = [_record("A", "AIR STACK", 1.0), _record("A", FUGITIVE, 2.0)]
    assert fold_fugitive(both, FUGITIVE, ALIASES).worker_only == []
    other_medium = [_record("A", "WATER", 1.0), _record("A", FUGITIVE, 2.0)]
    assert fold_fugitive(other_medium, FUGITIVE, ALIASES).worker_only == []


def test_stack_numbers_are_unchanged_by_the_worker_only_facilities() -> None:
    stack = [_record("A", "AIR STACK", 100.0), _record("B", "AIR STACK", 7.0)]
    without = fold_fugitive(stack, FUGITIVE, ALIASES)
    extra = [*stack, _record("C", FUGITIVE, 9.0), _record("D", FUGITIVE, 1.0)]
    with_extra = fold_fugitive(extra, FUGITIVE, ALIASES)
    assert with_extra.stack == without.stack
    assert [r["emission_rate"] for r in with_extra.stack] == [1.0, 1.0]
    assert [w["frs_id"] for w in with_extra.worker_only] == ["C", "D"]


def test_worker_only_unconvertible_unit_gives_no_release_and_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        found = fold_fugitive([_record("B", FUGITIVE, 5.0, unit="Gallons")], FUGITIVE, ALIASES)
    (only,) = found.worker_only
    assert only["fugitive_release_kg_per_year"] is None
    assert only["fugitive_reporting_year"] is None
    assert "Gallons" in caplog.text
