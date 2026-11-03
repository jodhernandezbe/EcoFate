"""Settings of the bulk FRS-to-EIS lookup and the same-site search (``[frs_eis]``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import read_toml, require_int, require_number, require_str, section

_NAME = "frs_eis"


@dataclass(frozen=True)
class FrsEisSettings:
    """Where the inventory reads the EIS (NEI) facility IDs of many FRS IDs in one request.

    Attributes:
        base_url: Service root URL (the same service as the FRS point lookup).
        eis_path: Path template with ``{frs_ids}`` (comma-separated FRS IDs); lists the EIS
            program registrations of those FRS IDs.
        registry_field: Answer column holding the FRS ID of a registration row.
        eis_id_field: Answer column holding the EIS facility ID of a registration row.
        sites_path: Path template with ``{frs_ids}``; the FRS site rows (name, state,
            coordinates) of those FRS IDs.
        twins_path: Path template with ``{names}`` (comma-separated, URL-encoded) and
            ``{state}``; the FRS site rows registered under any of those site names in that state.
        twin_single_path: Path template with ``{name}`` and ``{state}`` (URL-encoded); the same
            for one exact name, used for names that cannot go in a list (they contain a comma).
        name_field: Site-row column holding the site name.
        state_field: Site-row column holding the state postal code.
        latitude_field: Site-row column with the latitude, decimal degrees.
        longitude_field: Site-row column with the longitude, decimal degrees (west negative).
        batch_size: Most FRS IDs asked in one request.
        max_twin_distance_km: Farthest a same-named FRS record may lie from the facility to
            count as the same site.
        twin_list_pattern: Regular expression a site name must fully match to be searched
            (the service rejects the others, listed or alone).
        twin_batch_size: Most site names asked in one same-site request.
        twin_workers: Same-site requests run at the same time.
        cache_seconds: How long a facility's EIS IDs (or the reason it has none) are reused.
    """

    base_url: str
    eis_path: str
    registry_field: str
    eis_id_field: str
    sites_path: str
    twins_path: str
    twin_single_path: str
    name_field: str
    state_field: str
    latitude_field: str
    longitude_field: str
    batch_size: int
    max_twin_distance_km: float
    twin_list_pattern: re.Pattern[str]
    twin_batch_size: int
    twin_workers: int
    cache_seconds: float


def _template(table: dict[str, object], key: str, *slots: str) -> str:
    template = require_str(table, key, _NAME).strip()
    missing = [slot for slot in slots if slot not in template]
    if not template.startswith("/") or missing:
        raise ValueError(f"{_NAME}.{key} must start with / and contain {', '.join(slots)}")
    return template


def _text(table: dict[str, object], key: str) -> str:
    return require_str(table, key, _NAME).strip()


def _pattern(table: dict[str, object]) -> re.Pattern[str]:
    text = _text(table, "twin_list_pattern")
    try:
        return re.compile(text)
    except re.error as exc:
        raise ValueError(f"{_NAME}.twin_list_pattern is not a valid regular expression") from exc


def _fields(table: dict[str, object]) -> dict[str, str]:
    """The answer-column names, each a non-empty string."""
    names = ("registry_field", "eis_id_field", "name_field", "state_field", "latitude_field")
    return {key: _text(table, key) for key in (*names, "longitude_field")}


def load_frs_eis_settings(path: Path | None = None) -> FrsEisSettings:
    """Load and validate the ``[frs_eis]`` table.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    max_twin_km = require_number(table, "max_twin_distance_km", minimum=1e-9, name=_NAME)
    return FrsEisSettings(
        base_url=_text(table, "base_url"),
        eis_path=_template(table, "eis_path", "{frs_ids}"),
        sites_path=_template(table, "sites_path", "{frs_ids}"),
        twins_path=_template(table, "twins_path", "{names}", "{state}"),
        twin_single_path=_template(table, "twin_single_path", "{name}", "{state}"),
        **_fields(table),
        batch_size=require_int(table, "batch_size", minimum=1, name=_NAME),
        max_twin_distance_km=max_twin_km,
        twin_list_pattern=_pattern(table),
        twin_batch_size=require_int(table, "twin_batch_size", minimum=1, name=_NAME),
        twin_workers=require_int(table, "twin_workers", minimum=1, name=_NAME),
        cache_seconds=require_number(table, "cache_seconds", minimum=0, name=_NAME),
    )


@lru_cache(maxsize=1)
def get_frs_eis_settings() -> FrsEisSettings:
    """Return the cached FRS-EIS settings from the default file."""
    return load_frs_eis_settings()
