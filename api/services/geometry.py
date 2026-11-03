"""Drawing geometry: the receptor circle and the schematic downwind sector as GeoJSON polygons.

Pure spherical geometry for drawing only; it never models dispersion. Bearings are degrees
clockwise from north, distances kilometres, positions decimal degrees (WGS84).
"""

from __future__ import annotations

import math

from api.schemas.workspace import Polygon

EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius, km


def destination(
    latitude: float,
    longitude: float,
    bearing_deg: float,
    distance_km: float,
) -> list[float]:
    """The ``[longitude, latitude]`` reached from a point along a great circle."""
    lat1, lon1, theta = math.radians(latitude), math.radians(longitude), math.radians(bearing_deg)
    delta = distance_km / EARTH_RADIUS_KM
    lat2 = math.asin(
        math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(theta),
    )
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    return [(math.degrees(lon2) + 540.0) % 360.0 - 180.0, math.degrees(lat2)]


def _bearings(start: float, end: float, spacing: float) -> list[float]:
    """Bearings from ``start`` down to ``end`` (counter-clockwise on a north-up map)."""
    steps = max(math.ceil((start - end) / spacing), 1)
    return [start - (start - end) * i / steps for i in range(steps + 1)]


def circle(latitude: float, longitude: float, radius_km: float, spacing_deg: float) -> Polygon:
    """A closed ring of positions ``radius_km`` from the centre, counter-clockwise."""
    ring = [
        destination(latitude, longitude, bearing, radius_km)
        for bearing in _bearings(360.0, 0.0, spacing_deg)
    ]
    return Polygon(coordinates=[ring])


def sector(
    latitude: float,
    longitude: float,
    toward_deg: float,
    radius_km: float,
    half_angle_deg: float,
    spacing_deg: float,
) -> Polygon:
    """A wedge from the centre toward a bearing: ``radius_km`` long, ``2 * half_angle_deg`` wide."""
    arc = [
        destination(latitude, longitude, bearing, radius_km)
        for bearing in _bearings(
            toward_deg + half_angle_deg,
            toward_deg - half_angle_deg,
            spacing_deg,
        )
    ]
    centre = [longitude, latitude]
    return Polygon(coordinates=[[centre, *arc, centre]])
