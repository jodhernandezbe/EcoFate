"""Typed loader for the ``[population]`` settings (population receptors tool)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from config.parsing import (
    as_table,
    read_toml,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)
from config.policy import RequestPolicy, parse_policy

AGE_BANDS = ("0-4", "5-17", "18-64", "65+")
_NAME = "population"
TRACT_FIELDS = ("state", "county", "tract", "land_area", "latitude", "longitude")
ACS_VARIABLES = ("total", "under_5", "under_18", "over_65")
_BANDS_SUM_TOLERANCE = 0.5


@dataclass(frozen=True)
class PopulationDefault:
    """Population returned when no census data can be used.

    Attributes:
        residents_per_km2: Residents per square kilometre, applied to the circle's area.
        age_distribution: Age band (see ``AGE_BANDS``) -> percent of residents (sums to 100).
    """

    residents_per_km2: float
    age_distribution: Mapping[str, float]


@dataclass(frozen=True)
class PopulationSettings:
    """Census services, limits and the screening default for the population tool.

    Attributes:
        tract_url: TIGERweb census-tract query URL.
        acs_base_url: Census Data API root URL, without trailing slash.
        acs_path: Path template with ``{year}``, appended to ``acs_base_url``.
        acs_year: ACS 5-year vintage.
        api_key_env_var: Name of the environment variable holding the Census API key.
        default_radius_km: Radius used when none is given.
        min_radius_km: Smallest accepted radius.
        max_radius_km: Largest accepted radius.
        max_counties: Most counties (ACS requests) one call may reach.
        max_tracts_listed: Most tracts the result lists (the nearest); the rest are counted.
        policy: Delay, timeout and retry values.
        fields: Meaning (see ``TRACT_FIELDS``) -> TIGERweb field name.
        variables: Meaning (see ``ACS_VARIABLES``) -> ACS variable code.
        screening_default: Values returned when no census data can be used.
    """

    tract_url: str
    acs_base_url: str
    acs_path: str
    acs_year: int
    api_key_env_var: str
    default_radius_km: float
    min_radius_km: float
    max_radius_km: float
    max_counties: int
    max_tracts_listed: int
    policy: RequestPolicy
    fields: Mapping[str, str]
    variables: Mapping[str, str]
    screening_default: PopulationDefault

    @property
    def acs_url(self) -> str:
        """Full URL of the ACS dataset for the configured vintage."""
        return self.acs_base_url.rstrip("/") + self.acs_path.format(year=self.acs_year)


def _names(table: dict[str, object], name: str, expected: tuple[str, ...]) -> Mapping[str, str]:
    unknown = sorted(set(table) - set(expected))
    if unknown:
        raise ValueError(f"{name} has unknown keys: {', '.join(unknown)}")
    return MappingProxyType({key: require_str(table, key, name).strip() for key in expected})


def _mapping(table: dict[str, object], key: str, expected: tuple[str, ...]) -> Mapping[str, str]:
    name = "population"
    return _names(subtable(table, key, name), f"{name}.{key}", expected)


def _cap(table: dict[str, object], key: str) -> int:
    return require_int(table, key, minimum=1, name="population")


def _radii(table: dict[str, object]) -> tuple[float, float, float]:
    name = "population"
    low = require_number(table, "min_radius_km", minimum=1e-9, name=name)
    default = require_number(table, "default_radius_km", minimum=1e-9, name=name)
    high = require_number(table, "max_radius_km", minimum=1e-9, name=name)
    if not low <= default <= high:
        raise ValueError(
            "population radii must satisfy min_radius_km <= default_radius_km <= max_radius_km",
        )
    return low, default, high


def _acs_path(table: dict[str, object]) -> str:
    path = require_str(table, "acs_path", "population").strip()
    if not path.startswith("/") or "{year}" not in path:
        raise ValueError("population.acs_path must start with / and contain {year}")
    return path


def _screening_default(table: dict[str, object]) -> PopulationDefault:
    name = "population.screening_default"
    block = subtable(table, "screening_default", "population")
    bands_table = as_table(block.get("age_distribution"), f"{name}.age_distribution")
    unknown = sorted(set(bands_table) - set(AGE_BANDS))
    if unknown:
        raise ValueError(f"{name}.age_distribution has unknown bands: {', '.join(unknown)}")
    bands = {
        band: require_number(bands_table, band, minimum=0, name=f"{name}.age_distribution")
        for band in AGE_BANDS
    }
    if not math.isclose(sum(bands.values()), 100.0, abs_tol=_BANDS_SUM_TOLERANCE):
        raise ValueError(f"{name}.age_distribution must sum to 100 (got {sum(bands.values()):g})")
    density = require_number(block, "residents_per_km2", minimum=0, name=name)
    return PopulationDefault(density, MappingProxyType(bands))


def load_population_settings(path: Path | None = None) -> PopulationSettings:
    """Load and validate the population settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    low, default, high = _radii(table)
    return PopulationSettings(
        tract_url=require_str(table, "tract_url", _NAME).strip(),
        acs_base_url=require_str(table, "acs_base_url", _NAME).strip(),
        acs_path=_acs_path(table),
        acs_year=require_int(table, "acs_year", minimum=2009, name=_NAME),
        api_key_env_var=require_str(table, "api_key_env_var", _NAME).strip(),
        default_radius_km=default,
        min_radius_km=low,
        max_radius_km=high,
        max_counties=_cap(table, "max_counties"),
        max_tracts_listed=_cap(table, "max_tracts_listed"),
        policy=parse_policy(table, _NAME),
        fields=_mapping(table, "fields", TRACT_FIELDS),
        variables=_mapping(table, "variables", ACS_VARIABLES),
        screening_default=_screening_default(table),
    )


@lru_cache(maxsize=1)
def get_population_settings() -> PopulationSettings:
    """Return the cached population settings from the default file."""
    return load_population_settings()
