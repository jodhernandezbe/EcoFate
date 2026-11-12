"""Typed loader for the ``[osha_cehd]`` settings (OSHA monitoring data summary)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import cast

from config.parsing import (
    names,
    project_path,
    read_toml,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)

NAME = "osha_cehd"
ALLOWED_UNITS = ("mg/m^3", "ppm")


@dataclass(frozen=True)
class OshaCehdSettings:
    """Where the OSHA monitoring data comes from and how it is summarised.

    Attributes:
        url_pattern: Yearly ZIP URL with a ``{year}`` placeholder.
        crosswalk_url_pattern: OSHA chemical listing URL with a ``{page}`` placeholder.
        user_agent: Browser-like User-Agent the OSHA site requires.
        timeout_s: Timeout of each download, s.
        years: Years of samples in the summary, ascending.
        naics_prefix_lengths: NAICS prefix lengths summarised, longest first.
        min_values: Fewest values a level needs to be used.
        molar_volume_l_per_mol: Molar volume of an ideal gas, L/mol.
        summary_path: The built summary file.
        crosswalk_path: The built IMIS code to CAS number file.
        units: OSHA unit code -> unit (``mg/m^3`` or ``ppm``).
        nondetect_qualifiers: Qualifiers that mark a non-detect.
        blank_marker: Text in a qualifier that marks a blank sample.
    """

    url_pattern: str
    crosswalk_url_pattern: str
    user_agent: str
    timeout_s: float
    years: tuple[int, ...]
    naics_prefix_lengths: tuple[int, ...]
    min_values: int
    molar_volume_l_per_mol: float
    summary_path: Path
    crosswalk_path: Path
    units: Mapping[str, str]
    nondetect_qualifiers: tuple[str, ...]
    blank_marker: str


def _pattern(table: dict[str, object], key: str, placeholder: str) -> str:
    value = require_str(table, key, NAME)
    if placeholder not in value:
        raise ValueError(f"{NAME}.{key} must contain {placeholder}")
    return value


def _positive(table: dict[str, object], key: str) -> float:
    return require_number(table, key, minimum=1e-9, name=NAME)


def _years(table: dict[str, object]) -> tuple[int, ...]:
    raw = table.get("years")
    items = cast(list[object], raw) if isinstance(raw, list) else []
    if not items or not all(type(y) is int and 1984 <= y <= 2100 for y in items):
        raise ValueError(f"{NAME}.years must be a non-empty list of years")
    years = tuple(cast(list[int], items))
    if list(years) != sorted(set(years)):
        raise ValueError(f"{NAME}.years must be ascending without repeats")
    return years


def _lengths(table: dict[str, object]) -> tuple[int, ...]:
    raw = table.get("naics_prefix_lengths")
    items = cast(list[object], raw) if isinstance(raw, list) else []
    if not items or not all(type(n) is int and 1 <= n <= 6 for n in items):
        raise ValueError(f"{NAME}.naics_prefix_lengths must be a list of lengths 1 to 6")
    lengths = tuple(cast(list[int], items))
    if list(lengths) != sorted(set(lengths), reverse=True):
        raise ValueError(f"{NAME}.naics_prefix_lengths must be descending without repeats")
    return lengths


def _units(table: dict[str, object]) -> Mapping[str, str]:
    block = subtable(table, "units", NAME)
    if not block:
        raise ValueError(f"{NAME}.units must not be empty")
    units = {code: require_str(block, code, f"{NAME}.units") for code in block}
    if not set(units.values()) <= set(ALLOWED_UNITS):
        raise ValueError(f"{NAME}.units values must be one of {ALLOWED_UNITS}")
    return MappingProxyType(units)


def load_osha_cehd_settings(path: Path | None = None) -> OshaCehdSettings:
    """Load and validate the OSHA monitoring settings.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), NAME)
    return OshaCehdSettings(
        url_pattern=_pattern(table, "url_pattern", "{year}"),
        crosswalk_url_pattern=_pattern(table, "crosswalk_url_pattern", "{page}"),
        user_agent=require_str(table, "user_agent", NAME),
        timeout_s=_positive(table, "timeout_s"),
        years=_years(table),
        naics_prefix_lengths=_lengths(table),
        min_values=require_int(table, "min_values", minimum=1, name=NAME),
        molar_volume_l_per_mol=_positive(table, "molar_volume_l_per_mol"),
        summary_path=project_path(table, "summary_path", NAME),
        crosswalk_path=project_path(table, "crosswalk_path", NAME),
        units=_units(table),
        nondetect_qualifiers=names(table, "nondetect_qualifiers", NAME, allow_empty=False),
        blank_marker=require_str(table, "blank_marker", NAME),
    )


@lru_cache(maxsize=1)
def get_osha_cehd_settings() -> OshaCehdSettings:
    """Return the cached OSHA monitoring settings from the default file."""
    return load_osha_cehd_settings()
