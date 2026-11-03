"""Validate and convert one source row of stack values into the configured target units."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from commons.units import UnitConversionError, convert
from config.stack import STACK_QUANTITIES, StackSettings

StackRow = Mapping[str, str | None]


def check_units_convertible(
    units: Mapping[str, str],
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> None:
    """Raise ``ValueError`` naming the quantity whose source unit cannot reach its target unit.

    This is a setup check (configuration error), run before any lookup.
    """
    for quantity in STACK_QUANTITIES:
        try:
            convert(1.0, units[quantity], settings.target_units[quantity], aliases)
        except UnitConversionError as exc:
            raise ValueError(f"stack unit for {quantity} is not convertible: {exc}") from exc


def _parse_number(raw: str | None) -> float | None:
    """Return the cell as a finite float, or None (empty, non-numeric, inf or nan)."""
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _quantity(
    raw: str | None,
    quantity: str,
    unit: str,
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> tuple[float | None, str | None]:
    """Return (value in the target unit, None) or (None, reason it was rejected)."""
    number = _parse_number(raw)
    if number is None:
        return None, f"{quantity} is missing or not a finite number ({raw!r})"
    target = settings.target_units[quantity]
    value = convert(number, unit, target, aliases)
    bounds = settings.ranges[quantity]
    if value <= 0 or not bounds.minimum <= value <= bounds.maximum:
        return None, (
            f"{quantity} {value:g} {target} is outside the plausible range "
            f"[{bounds.minimum:g}, {bounds.maximum:g}] {target}"
        )
    return value, None


def stack_values(
    row: StackRow,
    columns: Mapping[str, str],
    units: Mapping[str, str],
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> tuple[Mapping[str, float] | None, list[str]]:
    """Convert one row into all four stack quantities, or reject it.

    Args:
        row: Source row, column name -> cell text.
        columns: Quantity -> column of ``row``.
        units: Quantity -> unit the source reports it in (already checked convertible).
        settings: Target units and plausible ranges.
        aliases: Unit spelling -> Pint-parsable unit string.

    Returns:
        ``(values, [])`` with every quantity in its target unit (m, m, m/s, K), or
        ``(None, reasons)`` when any quantity is missing, non-finite, non-positive or out of
        range. Values are never partially returned.
    """
    values: dict[str, float] = {}
    problems: list[str] = []
    for quantity in STACK_QUANTITIES:
        raw = row.get(columns[quantity])
        value, problem = _quantity(raw, quantity, units[quantity], settings, aliases)
        if value is None:
            problems.append(problem or f"{quantity} is invalid")
        else:
            values[quantity] = value
    return (None, problems) if problems else (MappingProxyType(values), [])
