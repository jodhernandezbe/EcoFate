"""Read a value the CompTox IRIS endpoint writes as text, e.g. ``"4 x 10 -3 mg/kg-day"``."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

# One number, optionally "x 10 <exponent>", then one unit token; nothing before or after.
_VALUE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)"
    r"(?:\s*[x×]\s*10\s*\^?\s*(?P<exponent>[+-]?\d+))?"
    r"\s+(?P<unit>\S+)",
)


def read_iris_value(text: object, units: Sequence[str]) -> tuple[float, str] | None:
    """Read ``text`` as one number and one of ``units``, or refuse it.

    Accepts ``5 mg/m3`` and ``2 x 10 -5 mg/m3``. Anything else is refused: a range, an
    inequality, several values (also on separate lines), a number with no unit or with a unit
    not in ``units``, zero, and an overflow.

    Args:
        text: The endpoint's field.
        units: Unit spellings accepted, exactly as written.

    Returns:
        (value, unit as written), or None if the text cannot be read exactly.
    """
    if not isinstance(text, str):
        return None
    match = _VALUE.fullmatch(text.strip())
    if match is None or match["unit"] not in units:
        return None
    exponent = int(match["exponent"]) if match["exponent"] else 0
    if abs(exponent) > 30:
        return None
    value = float(f"{match['number']}e{exponent}")
    return (value, match["unit"]) if math.isfinite(value) and value > 0 else None
