"""Residents and age mix around a point, with a labelled default on failure."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from config.population import PopulationSettings
from models.receptors.population import age_bands, scale_to_circle
from tools.exposure.helpers.inputs import is_number, point_problem
from tools.exposure.helpers.population.census import (
    CensusError,
    Counts,
    Tract,
    fetch_counts,
    fetch_tracts,
)
from tools.exposure.helpers.population.tracts import TractList, tract_list
from tools.http import RetryingClient
from tools.schemas import Population

DEFAULT_SOURCE = "screening default"
_METERS_PER_KM = 1000.0


def screening_default(settings: PopulationSettings, radius_km: float, reason: str) -> Population:
    """Return the configured default population for the circle, labelled, with the reason."""
    default = settings.screening_default
    area_km2 = math.pi * radius_km**2
    return Population(
        total_population=round(default.residents_per_km2 * area_km2),
        age_distribution=dict(default.age_distribution),
        source=DEFAULT_SOURCE,
        warnings=[f"{reason}; using the {DEFAULT_SOURCE} (generic, not site-specific)"],
        tracts=[],
        tracts_not_listed=0,
    )


def _radius_problem(radius: object, settings: PopulationSettings) -> str | None:
    low, high = settings.min_radius_km, settings.max_radius_km
    if is_number(radius) and low <= float(radius) <= high:  # type: ignore[arg-type]
        return None
    return f"radius {radius!r} km is invalid: it must be a number from {low:g} to {high:g} km"


@dataclass(frozen=True)
class _Tally:
    """Counts of the tracts that had usable estimates."""

    counts: Counts
    land_area_m2: float
    used: int
    left_out: int
    found: tuple[tuple[Tract, Counts], ...] = ()


def _sum(found: list[tuple[Tract, Counts]]) -> tuple[Counts, float]:
    counts = Counts(
        total=sum(c.total for _, c in found),
        under_5=sum(c.under_5 for _, c in found),
        under_18=sum(c.under_18 for _, c in found),
        over_65=sum(c.over_65 for _, c in found),
    )
    return counts, sum(tract.land_area_m2 for tract, _ in found)


def _tally(
    tracts: list[Tract],
    settings: PopulationSettings,
    client: RetryingClient,
    api_key: str,
) -> _Tally:
    """Fetch every county's estimates and sum those of the intersecting tracts."""
    by_county: dict[tuple[str, str], list[Tract]] = defaultdict(list)
    for tract in tracts:
        by_county[(tract.state, tract.county)].append(tract)
    found: list[tuple[Tract, Counts]] = []
    for (state, county), members in by_county.items():
        table = fetch_counts(state, county, settings, client, api_key)
        found += [(t, c) for t in members if (c := table.get(t.tract)) is not None]
    counts, land = _sum(found)
    return _Tally(counts, land, len(found), len(tracts) - len(found), tuple(found))


def _bands_and_notes(
    tally: _Tally,
    settings: PopulationSettings,
) -> tuple[dict[str, float], list[str]]:
    c = tally.counts
    notes: list[str] = []
    if tally.left_out:
        total = tally.used + tally.left_out
        notes.append(f"{tally.left_out} of {total} tracts had no usable estimate and were left out")
    if c.total == 0:
        notes.append("the tracts report no residents")
        return dict.fromkeys(settings.screening_default.age_distribution, 0.0), notes
    return age_bands(c.total, c.under_5, c.under_18, c.over_65), notes


def _tract_notes(listing: TractList) -> list[str]:
    if not listing.no_point:
        return []
    return [f"{listing.no_point} tracts have no internal point and are not listed with a distance"]


def _result(
    tally: _Tally,
    radius_km: float,
    settings: PopulationSettings,
    latitude: float,
    longitude: float,
) -> Population:
    circle_m2 = math.pi * (radius_km * _METERS_PER_KM) ** 2
    scaled = scale_to_circle(tally.counts.total, circle_m2, tally.land_area_m2)
    bands, notes = _bands_and_notes(tally, settings)
    listing = tract_list(list(tally.found), latitude, longitude, settings.max_tracts_listed)
    return Population(
        total_population=round(scaled),
        age_distribution=bands,
        source=f"Census ACS {settings.acs_year} 5-year (DP05), {tally.used} tracts",
        warnings=[*notes, *_tract_notes(listing)],
        tracts=listing.listed,
        tracts_not_listed=listing.not_listed,
    )


def population_around(
    latitude: float,
    longitude: float,
    radius_km: float | None,
    settings: PopulationSettings,
    client: RetryingClient,
    api_key: str,
) -> Population:
    """Estimate the residents within a radius of a point and their age mix.

    Args:
        latitude: Center latitude, decimal degrees.
        longitude: Center longitude, decimal degrees.
        radius_km: Search radius in kilometres, or None for the configured default.
        settings: Census services, limits and the screening default.
        client: Throttled, retrying HTTP client (injected).
        api_key: Census API key (may be empty); sent to the Census Data API only, never
            logged or returned.

    Returns:
        Residents (persons) and age bands (percent) from the ACS 5-year estimates of the
        intersecting tracts, scaled to the circle; the labelled screening default (with the
        reason) when the inputs are invalid, the key is missing or refused, a service fails,
        or no usable estimate exists. Data and network problems never raise.
    """
    radius = settings.default_radius_km if radius_km is None else radius_km
    problem = point_problem(latitude, longitude) or _radius_problem(radius, settings)
    if problem is not None:
        return screening_default(settings, settings.default_radius_km, problem)
    return _estimate(latitude, longitude, float(radius), settings, client, api_key)


class _Unusable(Exception):
    """The census data cannot be used; the message is the reason for the default."""


def _locate(
    latitude: float,
    longitude: float,
    radius_km: float,
    settings: PopulationSettings,
    client: RetryingClient,
    api_key: str,
) -> _Tally:
    if not api_key.strip():
        raise _Unusable(
            f"the Census API key is not set (environment variable {settings.api_key_env_var})",
        )
    tracts = fetch_tracts(latitude, longitude, radius_km * _METERS_PER_KM, settings, client)
    if not tracts:
        raise _Unusable("no census tract was found (open water or outside the United States)")
    counties = {(t.state, t.county) for t in tracts}
    if len(counties) > settings.max_counties:
        raise _Unusable(
            f"the circle reaches {len(counties)} counties, "
            f"above the limit of {settings.max_counties}",
        )
    tally = _tally(tracts, settings, client, api_key)
    if tally.used == 0:
        raise _Unusable("no intersecting tract had usable estimates")
    return tally


def _estimate(
    latitude: float,
    longitude: float,
    radius_km: float,
    settings: PopulationSettings,
    client: RetryingClient,
    api_key: str,
) -> Population:
    try:
        tally = _locate(latitude, longitude, radius_km, settings, client, api_key)
        return _result(tally, radius_km, settings, latitude, longitude)
    except _Unusable as exc:
        return screening_default(settings, radius_km, str(exc))
    except CensusError as exc:
        return screening_default(settings, radius_km, f"census data unavailable: {exc}")
    except ValueError as exc:
        return screening_default(
            settings,
            radius_km,
            f"the census estimates are inconsistent ({exc})",
        )
