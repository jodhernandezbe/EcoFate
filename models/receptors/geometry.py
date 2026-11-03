"""Where a receptor lies from a facility: great-circle distance and compass bearing."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius (IUGG), in meters (m)
_FULL_TURN_DEG = 360.0


def _check_point(latitude: float, longitude: float, name: str) -> None:
    finite = all(not isinstance(v, bool) and math.isfinite(v) for v in (latitude, longitude))
    if not finite or not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError(
            f"{name} must be a finite latitude in [-90, 90] and longitude in [-180, 180]",
        )


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points by the haversine formula.

    Args:
        lat1: Latitude of the first point, in degrees; [-90, 90].
        lon1: Longitude of the first point, in degrees; [-180, 180].
        lat2: Latitude of the second point, in degrees; [-90, 90].
        lon2: Longitude of the second point, in degrees; [-180, 180].

    Returns:
        Distance in meters (m) on a sphere of the mean Earth radius; 0 for the same point.

    Raises:
        ValueError: If a coordinate is not finite or is out of range.
    """
    _check_point(lat1, lon1, "the first point")
    _check_point(lat2, lon2, "the second point")
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing from the first point to the second.

    Args:
        lat1: Latitude of the origin, in degrees; [-90, 90].
        lon1: Longitude of the origin, in degrees; [-180, 180].
        lat2: Latitude of the target, in degrees; [-90, 90].
        lon2: Longitude of the target, in degrees; [-180, 180].

    Returns:
        Degrees clockwise from north, in [0, 360) (0 for the same point).

    Raises:
        ValueError: If a coordinate is not finite or is out of range.
    """
    _check_point(lat1, lon1, "the first point")
    _check_point(lat2, lon2, "the second point")
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    if x == 0.0 and y == 0.0:
        return 0.0
    return math.degrees(math.atan2(y, x)) % _FULL_TURN_DEG
