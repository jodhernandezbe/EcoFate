"""Reading one PubChem statement as a number with a unit (and a temperature), or refusing it.

PubChem's experimental values are free text. Only a statement that is one number, one unit and
at most one temperature is read; ranges, inequalities, estimates, several values and unitless
numbers (a relative density, for example) are refused with a reason, never guessed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from tools.informatics.helpers.pubchem.record import Statement

_NUMBER = r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_WORD = r"[A-Za-z][\w/^*.\-]*"
_UNIT = rf"(?:\[(?P<bracketed>{_WORD}(?: {_WORD})?)\]|(?P<plain>{_WORD}(?: {_WORD})?))"
_TEMPERATURE = rf"(?:\s*(?:at|@)\s*(?P<temp>{_NUMBER})\s*°?\s*(?P<scale>[CF]))"
_VALUE_FIRST = re.compile(rf"^(?P<value>{_NUMBER})\s*{_UNIT}{_TEMPERATURE}?$", re.IGNORECASE)
_LABELLED = re.compile(
    rf"^[^:,\d]+,\s*{_UNIT}{_TEMPERATURE}?\s*:\s*(?P<value>{_NUMBER})$",
    re.IGNORECASE,
)
_LONE_NUMBER = re.compile(rf"^{_NUMBER}$")
# Words Pint would read as a unit (technical atmosphere) but that here are only the "at" of
# "at 25 C".
_NOT_UNITS = frozenset({"at"})
_REFUSED = "not a single number with a unit (a range, estimate, several values or no unit)"


@dataclass(frozen=True)
class Reading:
    """One clear statement.

    Attributes:
        value: The number, in ``unit``, as written.
        unit: The unit as written, e.g. ``"mm Hg"``.
        celsius: The temperature the statement names, in degC, or None if it names none.
    """

    value: float
    unit: str
    celsius: float | None


def _celsius(match: re.Match[str]) -> float | None:
    temp = match.groupdict().get("temp")
    if temp is None:
        return None
    degrees = float(temp)
    return (degrees - 32.0) * 5.0 / 9.0 if match.group("scale").upper() == "F" else degrees


def _from_match(match: re.Match[str]) -> Reading | str:
    unit = (match.group("bracketed") or match.group("plain")).strip()
    if unit.lower() in _NOT_UNITS:
        return _REFUSED
    value = float(match.group("value"))
    if not math.isfinite(value):
        return "the number is not finite"
    return Reading(value, unit, _celsius(match))


def read_statement(statement: Statement) -> Reading | str:
    """Read ``statement`` as one value with a unit.

    Args:
        statement: A string of a PubChem entry, with the entry's separate unit if it has one.

    Returns:
        The reading, or the reason the statement was refused.
    """
    text = statement.text.strip()
    if statement.unit is not None:
        if not _LONE_NUMBER.match(text):
            return "a unit is given but the text is not a single number"
        return Reading(float(text), statement.unit, None)
    for pattern in (_VALUE_FIRST, _LABELLED):
        match = pattern.match(text)
        if match:
            return _from_match(match)
    return _REFUSED
