"""Validation of a value the user enters for a missing quantity (fail closed).

A value is accepted only when it is a finite number (never a boolean), its unit is one the
quantity accepts, it converts exactly to the target unit, and it lies inside the plausible range.
A value that fails any check is rejected with a reason; it is never clipped or defaulted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from langchain_core.runnables import RunnableConfig

from commons.units import UnitConversionError, convert
from config.user_values import UserValueSettings
from tools.schemas import MissingEntry


@dataclass(frozen=True)
class CheckedValue:
    """Outcome of checking one entered value.

    Attributes:
        value: The number in the quantity's target unit, or None when rejected.
        reason: Why it was rejected, or None when accepted.
    """

    value: float | None
    reason: str | None


def _rejected(reason: str) -> CheckedValue:
    return CheckedValue(value=None, reason=reason)


def _finite_number(number: object) -> float | None:
    """Return ``number`` as a float if it is a finite real number; None for anything else."""
    if isinstance(number, bool) or not isinstance(number, int | float):
        return None
    value = float(number)
    return value if math.isfinite(value) else None


def _unit_problem(quantity: str, unit: str, settings: UserValueSettings) -> str | None:
    accepted = settings.units[quantity]
    if unit in accepted:
        return None
    return f"{quantity} is not given in {unit!r}; accepted units: {', '.join(accepted)}"


def _in_range(quantity: str, value: float, settings: UserValueSettings) -> str | None:
    bounds = settings.ranges[quantity]
    if bounds.minimum <= value <= bounds.maximum:
        return None
    target = settings.units[quantity][0]
    return (
        f"{quantity} must be between {bounds.minimum:g} and {bounds.maximum:g} {target}; "
        f"the value given is outside that range"
    )


def _to_target(
    quantity: str,
    number: float,
    unit: str,
    settings: UserValueSettings,
    aliases: Mapping[str, str],
) -> float | CheckedValue:
    """Return the converted number, or the rejection when the conversion fails."""
    target = settings.units[quantity][0]
    try:
        return convert(number, unit, target, aliases)
    except UnitConversionError as exc:
        return _rejected(str(exc))


def check_entered_value(
    quantity: str,
    number: object,
    unit: str,
    settings: UserValueSettings,
    aliases: Mapping[str, str],
) -> CheckedValue:
    """Check a value the user entered and convert it to the quantity's target unit.

    Args:
        quantity: A quantity in ``settings.units``, e.g. ``"vapor_pressure"``.
        number: The entered magnitude, as typed; booleans and non-numbers are rejected.
        unit: The unit the user chose; must be one the quantity accepts.
        settings: Accepted units and plausible ranges.
        aliases: Source unit spelling -> Pint-parsable unit string.

    Returns:
        The accepted value in the target unit, or a rejection with the reason.
    """
    if quantity not in settings.units:
        return _rejected(f"{quantity!r} is not a quantity a value can be entered for")
    value = _finite_number(number)
    if value is None:
        return _rejected(f"{quantity} must be a finite number, not {number!r}")
    problem = _unit_problem(quantity, unit, settings)
    if problem is not None:
        return _rejected(problem)
    converted = _to_target(quantity, value, unit, settings, aliases)
    if isinstance(converted, CheckedValue):
        return converted
    out_of_range = _in_range(quantity, converted, settings)
    if out_of_range is not None:
        return _rejected(out_of_range)
    return CheckedValue(value=converted, reason=None)


def entry_id(quantity: str, subject: str) -> str:
    """The key of one value: the quantity and the chemical it belongs to."""
    return f"{quantity}:{subject}"


def missing_entry(
    quantity: str,
    subject: str,
    purpose: str,
    settings: UserValueSettings,
) -> MissingEntry:
    """Describe one missing value so the user can be asked for it."""
    bounds = settings.ranges[quantity]
    return MissingEntry(
        entry_id=entry_id(quantity, subject),
        quantity=quantity,
        subject=subject,
        accepted_units=list(settings.units[quantity]),
        minimum=bounds.minimum,
        maximum=bounds.maximum,
        purpose=purpose,
    )


def supplied_value(
    quantity: str,
    subject: str,
    supplied: Mapping[str, float],
    settings: UserValueSettings,
    aliases: Mapping[str, str],
) -> float | None:
    """The value the user supplied for this quantity and subject, re-checked; None if absent.

    The value was checked when the user answered; it is checked again here, in the target unit,
    so a tool never trusts a number it was handed.
    """
    key = entry_id(quantity, subject)
    if key not in supplied:
        return None
    target = settings.units[quantity][0]
    result = check_entered_value(quantity, supplied[key], target, settings, aliases)
    return result.value


@dataclass(frozen=True)
class UserValueInputs:
    """What the user has answered in this thread: values to use and entries declined.

    Attributes:
        settings: Accepted units and plausible ranges.
        aliases: Unit spelling aliases for the converter.
        supplied: entry_id -> value in the quantity's target unit, as checked when answered.
        declined: entry_ids the user chose to proceed without; they are not asked again.
    """

    settings: UserValueSettings
    aliases: Mapping[str, str]
    supplied: Mapping[str, float]
    declined: frozenset[str]


def _configured(config: RunnableConfig | None) -> Mapping[str, object]:
    """The ``user_values`` entry of a run's configurable settings, or an empty mapping."""
    if config is None:
        return {}
    configurable = config.get("configurable") or {}
    raw = configurable.get("user_values")
    return cast(Mapping[str, object], raw) if isinstance(raw, dict) else {}


def user_value_inputs(
    config: RunnableConfig | None,
    settings: UserValueSettings,
    aliases: Mapping[str, str],
) -> UserValueInputs:
    """Read the thread's answers from a tool's run configuration (nothing when absent)."""
    raw = _configured(config)
    supplied = raw.get("supplied")
    declined = raw.get("declined")
    return UserValueInputs(
        settings=settings,
        aliases=aliases,
        supplied=cast(Mapping[str, float], supplied) if isinstance(supplied, dict) else {},
        declined=frozenset(cast(list[str], declined))
        if isinstance(declined, list)
        else frozenset(),
    )
