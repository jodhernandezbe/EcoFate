"""A facility's total annual air release: stack plus fugitive, in kg/yr, or why it has none."""

from __future__ import annotations

import math

from api.schemas.workspace import Facility
from commons.units import UnitConversionError, convert
from config.air_release import AirReleaseRules


def _finite(value: float | None) -> float | None:
    """The value when it is a finite number (a bool never is), else None."""
    if isinstance(value, bool) or value is None or not math.isfinite(value):
        return None
    return float(value)


def _stack_kg(facility: Facility, rules: AirReleaseRules) -> float | None:
    """The stack release in kg/yr; raises ``UnitConversionError`` when it cannot be converted."""
    if facility.total_release is None:
        return None
    if facility.release_unit is None:
        raise UnitConversionError("the stack release has no unit")
    return convert(facility.total_release, facility.release_unit, rules.target_unit, rules.aliases)


def total_air_release(
    facility: Facility,
    rules: AirReleaseRules,
) -> tuple[float | None, str | None]:
    """The total (kg/yr) and the reason it is absent: exactly one of the two is None.

    Absent parts stay absent (never zero). An unconvertible stack unit (or a non-finite stack
    quantity) makes the total absent even when a fugitive release exists, which is never passed
    off as the total.
    """
    try:
        stack = _stack_kg(facility, rules)
    except UnitConversionError:
        return None, rules.reasons["unit_not_convertible"]
    parts = [p for p in (stack, _finite(facility.fugitive_release_kg_per_year)) if p is not None]
    if not parts:
        return None, rules.reasons["none_reported"]
    return sum(parts), None


def with_total_air_release(facility: Facility, rules: AirReleaseRules) -> Facility:
    """The facility with its total annual air release (or the reason it has none)."""
    total, reason = total_air_release(facility, rules)
    return facility.model_copy(
        update={"total_air_release_kg_per_year": total, "total_air_release_reason": reason},
    )
