"""Unit conversion guardrail built on Pint."""

from __future__ import annotations

import math
import tokenize
from collections.abc import Mapping

import pint

_REGISTRY = pint.UnitRegistry()


class UnitConversionError(ValueError):
    """A value could not be converted to the requested unit."""


def _resolve(unit: str, aliases: Mapping[str, str]) -> str:
    stripped = unit.strip()
    return aliases.get(stripped, stripped)


_CONVERSION_ERRORS = (
    pint.errors.PintError,
    tokenize.TokenError,
    ValueError,
    TypeError,
    AttributeError,
    SyntaxError,
)


def _pint_convert(value: float, source: str, target: str) -> float:
    quantity = _REGISTRY.Quantity(value, source)  # pyright: ignore[reportUnknownMemberType]
    return float(quantity.to(target).magnitude)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def convert(
    value: float,
    from_unit: str,
    to_unit: str,
    aliases: Mapping[str, str] | None = None,
) -> float:
    """Convert ``value`` from ``from_unit`` to ``to_unit``.

    The configured ``aliases`` are applied to both unit strings first, so source spellings
    such as "mg/m3" can be mapped to ones Pint parses. Offset units (degF, degC) convert
    as absolute temperatures (32 degF -> 273.15 K); do not use them for temperature
    differences, and do not combine them with other units (e.g. "degC/s").

    Args:
        value: Magnitude in ``from_unit``. Must be finite.
        from_unit: Unit reported by the source, e.g. "ug/m3".
        to_unit: Target unit, e.g. "mg/m^3".
        aliases: Source spelling -> Pint-parsable unit string.

    Returns:
        The magnitude in ``to_unit``.

    Raises:
        UnitConversionError: If ``value`` is not finite, a unit cannot be parsed or is
            unknown, or the units have different dimensions. The message names both units;
            an unconverted number is never returned.
    """
    if not math.isfinite(value):
        raise UnitConversionError(f"cannot convert non-finite value {value!r}")
    table = aliases or {}
    try:
        result = _pint_convert(value, _resolve(from_unit, table), _resolve(to_unit, table))
    except _CONVERSION_ERRORS as exc:
        raise UnitConversionError(
            f"cannot convert from {from_unit!r} to {to_unit!r}: {exc}",
        ) from exc
    if not math.isfinite(result):
        raise UnitConversionError(f"conversion from {from_unit!r} to {to_unit!r} overflowed")
    return result
