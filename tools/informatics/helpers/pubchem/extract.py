"""The configured fields of a PubChem record, as values in their target units."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass

from commons.units import UnitConversionError, convert
from config.pubchem import FieldSpec
from tools.informatics.helpers.pubchem.record import find_sections, statements
from tools.informatics.helpers.pubchem.result import Lookup
from tools.informatics.helpers.pubchem.statements import Reading, read_statement


@dataclass(frozen=True)
class FieldValue:
    """The value PubChem gives for one field.

    Attributes:
        value: In ``unit``, the field's target unit.
        unit: The target unit of the field.
        count: How many clear statements it comes from (the median when more than one).
    """

    value: float
    unit: str
    count: int


def _usable_temperature(reading: Reading, spec: FieldSpec) -> str | None:
    """None if the statement's temperature is acceptable for ``spec``, else why not."""
    if reading.celsius is None:
        return None if spec.allow_missing_temperature else "it names no temperature"
    low, high = spec.min_celsius, spec.max_celsius
    if low is not None and high is not None and not low <= reading.celsius <= high:
        return f"its temperature, {reading.celsius:.1f} degC, is outside {low:g} to {high:g} degC"
    return None


def _in_target(reading: Reading, spec: FieldSpec, aliases: Mapping[str, str]) -> float | str:
    """The reading in the target unit, or why it cannot be used."""
    problem = _usable_temperature(reading, spec)
    if problem is not None:
        return problem
    try:
        value = convert(reading.value, reading.unit, spec.target_unit, aliases)
    except UnitConversionError:
        return f"its unit {reading.unit!r} does not convert to {spec.target_unit}"
    return value if value > 0 else "the value is not greater than zero"


def _agreed(values: list[float], ratio: float) -> float | str:
    """The median of ``values``, or why they cannot be combined."""
    if max(values) / min(values) > ratio:
        return f"the {len(values)} statements disagree by more than a factor of {ratio:g}"
    return statistics.median(values)


def _candidates(
    record: object,
    spec: FieldSpec,
    aliases: Mapping[str, str],
) -> tuple[list[float], list[str]]:
    values: list[float] = []
    refused: list[str] = []
    for statement in statements(find_sections(record, spec.heading)):
        reading = read_statement(statement)
        outcome = _in_target(reading, spec, aliases) if isinstance(reading, Reading) else reading
        if isinstance(outcome, float):
            values.append(outcome)
        else:
            refused.append(f"{statement.text!r}: {outcome}")
    return values, refused


def extract_field(
    record: object,
    spec: FieldSpec,
    ratio: float,
    aliases: Mapping[str, str],
) -> Lookup[FieldValue]:
    """Read one configured field from a record.

    Only clear statements count: one number and one unit that converts to the target unit,
    and a temperature, if named, inside the field's window. Several clear statements give
    their median if they agree within ``ratio``; if they do not, there is no value.

    Args:
        record: The PUG View record (untrusted JSON).
        spec: The field: headings, target unit and temperature rule.
        ratio: Largest allowed max/min of several statements.
        aliases: Unit-spelling aliases for the unit converter.

    Returns:
        The value in the target unit, or the reason there is none.
    """
    values, refused = _candidates(record, spec, aliases)
    if not values:
        detail = f"; refused {len(refused)}, e.g. {refused[0]}" if refused else ""
        return Lookup[FieldValue].missing(f"PubChem has no usable {spec.key} statement{detail}")
    agreed = _agreed(values, ratio)
    if isinstance(agreed, str):
        return Lookup[FieldValue].missing(f"PubChem {spec.key}: {agreed}")
    return Lookup[FieldValue].found(FieldValue(agreed, spec.target_unit, len(values)))
