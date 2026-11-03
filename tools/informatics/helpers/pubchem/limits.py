"""Occupational exposure limits from a PUG View record, as numbers in mg/m^3.

Only a clear value is used: a named entry (``PEL-TWA``) holding one number and one unit, or a
free-text entry that one of the configured patterns reads. A value in ppm needs the molecular
weight; without it the value is refused, never converted with a guess. Several clear values
for one limit are used (their median) only if they agree.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Mapping, Sequence

from commons.units import UnitConversionError, convert
from config.pubchem import LimitSpec, LimitsSettings
from models.chemistry.air_units import ppm_to_mg_per_m3
from tools.informatics.helpers.pubchem.record import find_sections, named_statements
from tools.schemas import LimitValue, OccupationalLimits

_PLAIN = re.compile(r"^\s*\[?(?P<value>\d+(?:\.\d+)?)\s*\[?(?P<unit>[A-Za-z/^0-9³. ]+?)\]?\]?\s*$")
_TARGET = "mg/m^3"
_PPM = "ppm"


def _unit(raw: str, settings: LimitsSettings) -> str | None:
    return settings.units.get(raw.lower().replace(" ", ""))


def _to_mg_m3(
    value: float,
    unit: str,
    weight: float | None,
    settings: LimitsSettings,
) -> tuple[float, bool] | str:
    """The value in mg/m^3 and whether it came from ppm, or why it cannot be used."""
    if value <= 0:
        return "the value is not greater than zero"
    if unit == _PPM:
        if weight is None:
            return "it is in ppm and the molecular weight is unknown"
        return ppm_to_mg_per_m3(value, weight, settings.molar_volume_l_per_mol), True
    try:
        return convert(value, unit, _TARGET), False
    except UnitConversionError:
        return f"its unit {unit!r} does not convert to {_TARGET}"


def _match(spec: LimitSpec, name: str | None, text: str) -> re.Match[str] | None:
    """The match of the entry against the spec's name pattern or text patterns."""
    if spec.name_pattern is not None and name is not None and spec.name_pattern.search(name):
        return _PLAIN.match(text)
    for pattern in spec.text_patterns:
        found = pattern.search(text)
        if found:
            return found
    return None


def _candidates(
    record: object,
    spec: LimitSpec,
    weight: float | None,
    settings: LimitsSettings,
) -> tuple[list[tuple[float, bool]], list[str]]:
    values: list[tuple[float, bool]] = []
    refused: list[str] = []
    for name, statement in named_statements(find_sections(record, spec.heading)):
        found = _match(spec, name, statement.text)
        if found is None:
            continue
        unit = _unit(found.group("unit"), settings)
        if unit is None:
            refused.append(f"{statement.text!r}: unit {found.group('unit')!r} not recognised")
            continue
        outcome = _to_mg_m3(float(found.group("value")), unit, weight, settings)
        if isinstance(outcome, str):
            refused.append(f"{statement.text!r}: {outcome}")
        else:
            values.append(outcome)
    return values, refused


def _one(
    record: object,
    spec: LimitSpec,
    weight: float | None,
    settings: LimitsSettings,
    ratio: float,
) -> LimitValue | str:
    values, refused = _candidates(record, spec, weight, settings)
    if not values:
        detail = f"; refused {len(refused)}, e.g. {refused[0]}" if refused else ""
        return f"PubChem has no usable {spec.programme} statement{detail}"
    amounts = [v for v, _ in values]
    if max(amounts) / min(amounts) > ratio:
        return f"the {len(values)} {spec.programme} statements disagree by more than {ratio:g}x"
    return LimitValue(
        value=statistics.median(amounts),
        programme=spec.programme,
        converted_from_ppm=all(c for _, c in values),
        statements=len(values),
    )


def _benchmark(
    limits: Mapping[str, LimitValue],
    priority: Sequence[str],
) -> tuple[float | None, str | None]:
    for key in priority:
        if key in limits:
            return limits[key]["value"], f"{limits[key]['programme']} (PubChem)"
    return None, None


def empty_limits(reason: str) -> OccupationalLimits:
    """No limits at all, with the reason (no record, or not looked up)."""
    return OccupationalLimits(
        oel_twa_mg_m3=None,
        oel_source=None,
        limits={},
        reasons={},
        warnings=[reason],
    )


def read_limits(
    record: object,
    weight: float | None,
    settings: LimitsSettings,
    ratio: float,
) -> OccupationalLimits:
    """Read every configured limit from a PUG View record.

    Args:
        record: The PUG View record (untrusted JSON).
        weight: Molecular weight, g/mol, for ppm values; None if unknown.
        settings: The configured limits, units and TWA priority.
        ratio: Largest allowed max/min of several statements for one limit.

    Returns:
        The limits found in mg/m^3, the chosen 8-hour TWA benchmark with its source, and why
        any other limit is missing. Never raises on data problems.
    """
    found: dict[str, LimitValue] = {}
    reasons: dict[str, str] = {}
    for spec in settings.items:
        outcome = _one(record, spec, weight, settings, ratio)
        if isinstance(outcome, str):
            reasons[spec.key] = outcome
        else:
            found[spec.key] = outcome
    value, source = _benchmark(found, settings.twa_priority)
    warnings = [] if value is not None else ["PubChem lists no usable 8-hour TWA limit"]
    return OccupationalLimits(
        oel_twa_mg_m3=value,
        oel_source=source,
        limits=found,
        reasons=reasons,
        warnings=warnings,
    )
