"""Turn a CompTox IRIS endpoint record into toxicity values, and check them against ToxVal."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from config.iris import IrisFieldSpec, IrisSettings
from config.loader import ToxicityValueSpec
from tools.informatics.helpers.iris_text import read_iris_value
from tools.schemas import ToxicityValue

_NOT_STATED = ("", "-")


def _text(value: object) -> str | None:
    """Return ``value`` stripped if it is real text; the endpoint leaves a value out or says "-"."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return None if stripped in _NOT_STATED else stripped


def _systems(record: Mapping[str, object], iris: IrisSettings) -> str | None:
    """The critical-effect systems, one per line in the record, joined with ", "."""
    text = _text(record.get(iris.effects_field))
    if text is None:
        return None
    return ", ".join(line.strip() for line in text.splitlines() if line.strip()) or None


def _source(record: Mapping[str, object], iris: IrisSettings) -> str:
    revision = _text(record.get(iris.revision_field))
    return iris.source_revised.format(revision=revision) if revision else iris.source


def _value(
    record: Mapping[str, object],
    iris: IrisSettings,
    field: IrisFieldSpec,
    route: str,
) -> ToxicityValue | str | None:
    """The field's value; a note if its text cannot be read exactly; None if there is none."""
    text = _text(record.get(field.field))
    if text is None:
        return None
    read = read_iris_value(text, field.units)
    if read is None:
        return f"{field.key}: IRIS endpoint text {text!r} cannot be read exactly"
    return {
        "value": read[0],
        "unit": read[1],
        "source": _source(record, iris),
        "route": route,
        "endpoint": _systems(record, iris),
        "assessment": "non-cancer",
    }


def iris_values(
    record: Mapping[str, object],
    iris: IrisSettings,
    specs: Sequence[ToxicityValueSpec],
) -> tuple[dict[str, ToxicityValue], list[str]]:
    """Read the configured chronic values of one endpoint record.

    Returns:
        The values that could be read exactly (in the unit written, with the IRIS source, the
        route of the toxicity value, the critical-effect systems as endpoint and a non-cancer
        assessment), and a note for each text that was present but refused.
    """
    routes = {spec.key: spec.applied_route for spec in specs}
    values: dict[str, ToxicityValue] = {}
    notes: list[str] = []
    for field in iris.fields:
        found = _value(record, iris, field, routes[field.key])
        if isinstance(found, str):
            notes.append(found)
        elif found is not None:
            values[field.key] = found
    return values, notes


def disagreement(
    key: str,
    endpoint: ToxicityValue,
    toxval: ToxicityValue | None,
    tolerance: float,
) -> str | None:
    """A note if ToxVal's IRIS value differs from the endpoint's by more than ``tolerance``.

    Values in different units are not compared.
    """
    if toxval is None or toxval["unit"] != endpoint["unit"]:
        return None
    if abs(endpoint["value"] - toxval["value"]) <= tolerance * abs(endpoint["value"]):
        return None
    return (
        f"{key}: the IRIS endpoint gives {endpoint['value']:g} {endpoint['unit']} but the ToxVal "
        f"copy of IRIS gives {toxval['value']:g} {toxval['unit']}; the endpoint's value is used"
    )
