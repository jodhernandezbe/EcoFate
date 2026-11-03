"""The census tracts around a facility as receptors: residents, age mix, distance and bearing."""

from __future__ import annotations

from dataclasses import dataclass

from models.receptors.geometry import bearing_deg, distance_m
from models.receptors.population import age_bands
from tools.exposure.helpers.population.census import Counts, Tract
from tools.schemas import TractReceptor

_M2_PER_KM2 = 1e6


@dataclass(frozen=True)
class TractList:
    """The tracts listed, and what was not listed.

    Attributes:
        listed: Tracts with residents and an internal point, nearest first, up to the limit.
        not_listed: Tracts with residents and a point beyond the limit.
        no_point: Tracts with residents but no usable internal point (counted in the pooled
            result, never listed).
    """

    listed: list[TractReceptor]
    not_listed: int
    no_point: int


def _receptor(
    tract: Tract,
    counts: Counts,
    origin: tuple[float, float],
    point: tuple[float, float],
) -> TractReceptor:
    return TractReceptor(
        geoid=tract.state + tract.county + tract.tract,
        residents=round(counts.total),
        age_distribution=age_bands(counts.total, counts.under_5, counts.under_18, counts.over_65),
        distance_m=distance_m(*origin, *point),
        bearing_deg=bearing_deg(*origin, *point),
        latitude=point[0],
        longitude=point[1],
        land_area_km2=tract.land_area_m2 / _M2_PER_KM2,
    )


def tract_list(
    found: list[tuple[Tract, Counts]],
    latitude: float,
    longitude: float,
    limit: int,
) -> TractList:
    """List the tracts that have residents, nearest first.

    Args:
        found: Intersecting tracts with their ACS counts (persons).
        latitude: Facility latitude, decimal degrees.
        longitude: Facility longitude, decimal degrees.
        limit: Most tracts to list; the others are counted.

    Returns:
        The nearest ``limit`` tracts with residents and a point, and the counts of those not
        listed and of those without a point. A tract with no residents is neither.
    """
    populated = [(t, c) for t, c in found if c.total > 0]
    origin = (latitude, longitude)
    receptors = [
        _receptor(t, c, origin, (t.latitude, t.longitude))
        for t, c in populated
        if t.latitude is not None and t.longitude is not None
    ]
    receptors.sort(key=lambda r: r["distance_m"])
    no_point = len(populated) - len(receptors)
    return TractList(receptors[:limit], max(0, len(receptors) - limit), no_point)
