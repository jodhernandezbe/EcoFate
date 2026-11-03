"""Validation of the point (latitude, longitude) the exposure tools take as input."""

from __future__ import annotations

import math

MAX_LATITUDE = 90.0
MAX_LONGITUDE = 180.0


def is_number(value: object) -> bool:
    """Return True for a finite int or float that is not a bool."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def coordinate_problem(value: object, name: str, limit: float) -> str | None:
    """Return why ``value`` is not a coordinate within ``-limit`` to ``limit``, or None."""
    if is_number(value) and -limit <= float(value) <= limit:  # type: ignore[arg-type]
        return None
    return f"{name} {value!r} is invalid: it must be a finite number from -{limit:g} to {limit:g}"


def point_problem(latitude: object, longitude: object) -> str | None:
    """Return why the point is invalid, or None when both coordinates are valid."""
    return coordinate_problem(latitude, "latitude", MAX_LATITUDE) or coordinate_problem(
        longitude,
        "longitude",
        MAX_LONGITUDE,
    )
