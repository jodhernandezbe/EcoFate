"""A facility's total annual air release: stack converted to kg/yr plus fugitive, fail closed."""

from __future__ import annotations

import math

import pytest

from api.schemas.workspace import Facility
from api.services.projectors.air_release import total_air_release, with_total_air_release
from config.ui import get_ui_settings

RULES = get_ui_settings().air_release
POUND_KG = 0.45359237
# The unit spellings TRI reports for air releases (the inventory's `unit_of_measure`).
TRI_UNITS = {"Pounds": POUND_KG, "Grams": 0.001}


def _facility(
    total: float | None = None,
    unit: str | None = None,
    fugitive: float | None = None,
) -> Facility:
    return Facility(
        frs_id="F1",
        latitude=10.0,
        longitude=-20.0,
        reporting_year=2020,
        operating_hours_per_year=8760.0,
        total_release=total,
        release_unit=unit,
        fugitive_release_kg_per_year=fugitive,
    )


def test_stack_and_fugitive_are_summed_in_kg() -> None:
    total, reason = total_air_release(_facility(100.0, "Pounds", 5.0), RULES)
    assert total == pytest.approx(100.0 * POUND_KG + 5.0)
    assert reason is None


def test_stack_only() -> None:
    total, _ = total_air_release(_facility(10.0, "Pounds"), RULES)
    assert total == pytest.approx(10.0 * POUND_KG)


def test_worker_only_takes_its_fugitive_release() -> None:
    assert total_air_release(_facility(fugitive=7.5), RULES) == (7.5, None)


def test_a_zero_stack_release_is_a_reported_part() -> None:
    assert total_air_release(_facility(0.0, "Pounds", 2.0), RULES) == (2.0, None)


@pytest.mark.parametrize(("unit", "kg"), list(TRI_UNITS.items()))
def test_every_tri_unit_spelling_converts(unit: str, kg: float) -> None:
    total, reason = total_air_release(_facility(1000.0, unit), RULES)
    assert total == pytest.approx(1000.0 * kg) and reason is None


def test_unknown_unit_is_absent_even_with_a_fugitive_release() -> None:
    total, reason = total_air_release(_facility(5.0, "Furlongs", 9.0), RULES)
    assert total is None
    assert reason == RULES.reasons["unit_not_convertible"]


def test_a_stack_release_without_a_unit_is_absent() -> None:
    assert total_air_release(_facility(5.0, None, 9.0), RULES)[0] is None


def test_nothing_reported_is_absent_with_its_reason() -> None:
    assert total_air_release(_facility(), RULES) == (None, RULES.reasons["none_reported"])


@pytest.mark.parametrize("bad", [math.inf, math.nan])
def test_a_non_finite_stack_release_is_absent(bad: float) -> None:
    total, reason = total_air_release(_facility(bad, "Pounds", 3.0), RULES)
    assert total is None and reason == RULES.reasons["unit_not_convertible"]


def test_a_non_finite_fugitive_release_counts_as_absent() -> None:
    assert total_air_release(_facility(fugitive=math.inf), RULES)[0] is None


def test_the_facility_carries_the_total_or_the_reason_never_both() -> None:
    sized = with_total_air_release(_facility(fugitive=4.0), RULES)
    assert sized.total_air_release_kg_per_year == 4.0 and sized.total_air_release_reason is None
    bare = with_total_air_release(_facility(), RULES)
    assert bare.total_air_release_kg_per_year is None and bare.total_air_release_reason
