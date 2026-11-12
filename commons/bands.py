"""Three screening bands ("high", "moderate", "low") from values and their boundaries.

Generic and pure: the caller passes each value with its own lower and upper boundary (from its
configuration). A value at or above its upper boundary is "high"; otherwise at or above its lower
boundary "moderate"; otherwise "low". The band of several values is the highest any of them gives.
A missing value (None) does not count; with no value at all the band is None, never "low".
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

Band = Literal["high", "moderate", "low"]
BANDS: tuple[Band, ...] = ("low", "moderate", "high")


def _check(lower: float, upper: float) -> None:
    for name, value in (("lower", lower), ("upper", upper)):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} boundary must be a finite, positive number, got {value!r}")
    if lower >= upper:
        raise ValueError(f"lower boundary {lower!r} must be below upper boundary {upper!r}")


def band_of(value: float, lower: float, upper: float) -> Band:
    """The band of one value (unitless, in the unit of its boundaries).

    Raises:
        ValueError: If the value is not finite or negative, or the boundaries are invalid.
    """
    _check(lower, upper)
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f"value must be a finite, non-negative number, got {value!r}")
    if value >= upper:
        return "high"
    return "moderate" if value >= lower else "low"


def highest_band(values: Sequence[tuple[float | None, float, float]]) -> Band | None:
    """The highest band of ``(value, lower, upper)`` triples; None when every value is None."""
    found: list[Band] = [band_of(v, lo, up) for v, lo, up in values if v is not None]
    if not found:
        return None
    return BANDS[max(BANDS.index(b) for b in found)]
