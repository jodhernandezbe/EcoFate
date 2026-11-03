"""Typed loader for the ``[pubchem]`` settings (PubChem fallback for chemical properties)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast
from urllib.parse import quote

from config.loader import load_comptox_settings
from config.parsing import (
    as_table,
    names,
    project_path,
    read_toml,
    require_bool,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)

_NAME = "pubchem"
# PubChem asks for at most 5 requests a second; the wait before each request must be at least
# one fifth of a second.
MIN_DELAY_SECONDS = 0.2
# The result key of molecular weight (CompTox keeps it apart from the [[comptox.properties]]).
_WEIGHT_KEY = "molecular_weight"


@dataclass(frozen=True)
class CacheSettings:
    """The on-disk response cache.

    Attributes:
        enabled: Whether answers are cached at all.
        path: SQLite file, absolute or resolved against the project root.
        ttl_days: Days an answer stays valid.
    """

    enabled: bool
    path: Path
    ttl_days: float


@dataclass(frozen=True)
class FieldSpec:
    """One result field PubChem is asked for.

    Attributes:
        key: Field of the tool result, e.g. ``"vapor_pressure"``.
        heading: PUG View headings leading to the statements, outermost first.
        target_unit: Unit the value is converted to (the same as CompTox's for ``key``).
        min_celsius: Lowest temperature, in degC, a statement may name; None = no limit.
        max_celsius: Highest temperature, in degC, a statement may name; None = no limit.
        allow_missing_temperature: Whether a statement that names no temperature is used.
    """

    key: str
    heading: tuple[str, ...]
    target_unit: str
    min_celsius: float | None
    max_celsius: float | None
    allow_missing_temperature: bool


@dataclass(frozen=True)
class LimitSpec:
    """One occupational limit read from a record.

    Attributes:
        key: Name of the limit, e.g. ``"osha_pel"``.
        programme: Name shown with the value, e.g. ``"OSHA PEL-TWA"``.
        heading: PUG View headings leading to the entries, outermost first.
        name_pattern: Entries whose ``Name`` matches hold the value as a plain number and unit;
            None = no named entries are read.
        text_patterns: Patterns (named groups ``value`` and ``unit``) for free-text entries.
    """

    key: str
    programme: str
    heading: tuple[str, ...]
    name_pattern: re.Pattern[str] | None
    text_patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class LimitsSettings:
    """The occupational limits PubChem is asked for.

    Attributes:
        molar_volume_l_per_mol: Molar volume of a gas at 25 degC and 1 atm, L/mol.
        twa_priority: Limit keys in the order the 8-hour TWA benchmark is chosen.
        units: Unit spelling (lower case, no spaces) -> ``"ppm"`` or a Pint unit.
        items: The limits.
    """

    molar_volume_l_per_mol: float
    twa_priority: tuple[str, ...]
    units: Mapping[str, str]
    items: tuple[LimitSpec, ...]


@dataclass(frozen=True)
class PubchemSettings:
    """All PubChem settings.

    Attributes:
        cid_by_smiles_url: URL template with ``{smiles}``.
        cid_by_name_url: URL template with ``{name}`` (also used for CAS numbers).
        pug_view_url: URL template with ``{cid}``.
        user_agent: ``User-Agent`` header naming the application.
        delay_seconds: Wait before each request, in seconds (at least 0.2).
        timeout_seconds: Per-request timeout, in seconds.
        max_retries: Retries after a throttled, failed or timed-out request.
        backoff_seconds: First retry wait in seconds; doubles on each further retry.
        cas_heading: PUG View headings leading to the record's own CAS numbers.
        agreement_ratio: Largest allowed max/min ratio of several clear statements.
        cache: The response cache.
        fields: The result fields PubChem is asked for.
        limits: The occupational limits PubChem is asked for.
    """

    cid_by_smiles_url: str
    cid_by_name_url: str
    pug_view_url: str
    user_agent: str
    delay_seconds: float
    timeout_seconds: float
    max_retries: int
    backoff_seconds: float
    cas_heading: tuple[str, ...]
    agreement_ratio: float
    cache: CacheSettings
    fields: tuple[FieldSpec, ...]
    limits: LimitsSettings

    def smiles_url(self, smiles: str) -> str:
        """Return the CID search URL for ``smiles`` (URL-encoded)."""
        return self.cid_by_smiles_url.format(smiles=quote(smiles, safe=""))

    def name_url(self, name: str) -> str:
        """Return the CID search URL for a name or CAS number (URL-encoded)."""
        return self.cid_by_name_url.format(name=quote(name, safe=""))

    def record_url(self, cid: int) -> str:
        """Return the PUG View URL of ``cid``."""
        return self.pug_view_url.format(cid=cid)


def _template(table: dict[str, object], key: str, slot: str) -> str:
    name = f"{_NAME}.{key}"
    template = require_str(table, key, _NAME).strip()
    try:
        template.format(**{slot: "0"})
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"{name} must contain only the {{{slot}}} slot") from exc
    if f"{{{slot}}}" not in template:
        raise ValueError(f"{name} must contain {{{slot}}}")
    return template


def _delay(table: dict[str, object]) -> float:
    delay = require_number(table, "delay_seconds", minimum=0, name=_NAME)
    if delay < MIN_DELAY_SECONDS:
        raise ValueError(
            f"{_NAME}.delay_seconds must be at least {MIN_DELAY_SECONDS} "
            "(PubChem allows at most 5 requests a second)",
        )
    return delay


def _ratio(table: dict[str, object]) -> float:
    return require_number(table, "agreement_ratio", minimum=1, name=_NAME)


def _cache(table: dict[str, object]) -> CacheSettings:
    name = f"{_NAME}.cache"
    return CacheSettings(
        enabled=require_bool(table, "enabled", name),
        path=project_path(table, "path", name),
        ttl_days=require_number(table, "ttl_days", minimum=0.001, name=name),
    )


def _optional_celsius(table: dict[str, object], key: str, name: str) -> float | None:
    if key not in table:
        return None
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name}.{key} must be a number")
    return float(value)


def _field(raw: object, index: int) -> FieldSpec:
    name = f"{_NAME}.fields[{index}]"
    table = as_table(raw, name)
    low = _optional_celsius(table, "min_celsius", name)
    high = _optional_celsius(table, "max_celsius", name)
    if (low is None) != (high is None) or (low is not None and high is not None and low >= high):
        raise ValueError(f"{name}: min_celsius and max_celsius must both be set, min below max")
    return FieldSpec(
        key=require_str(table, "key", name).strip(),
        heading=names(table, "heading", name, allow_empty=False),
        target_unit=require_str(table, "target_unit", name).strip(),
        min_celsius=low,
        max_celsius=high,
        allow_missing_temperature=require_bool(table, "allow_missing_temperature", name),
    )


def _fields(table: dict[str, object]) -> tuple[FieldSpec, ...]:
    raw = table.get("fields")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{_NAME}.fields must be a non-empty list of tables")
    fields = tuple(_field(item, i) for i, item in enumerate(cast(list[object], raw)))
    if len({spec.key for spec in fields}) != len(fields):
        raise ValueError(f"{_NAME}.fields has a key listed twice")
    return fields


def _pattern(raw: str, name: str) -> re.Pattern[str]:
    try:
        compiled = re.compile(raw)
    except re.error as exc:
        raise ValueError(f"{name} is not a valid pattern: {exc}") from exc
    if not {"value", "unit"} <= set(compiled.groupindex):
        raise ValueError(f"{name} must have the named groups value and unit")
    return compiled


def _limit(raw: object, index: int) -> LimitSpec:
    name = f"{_NAME}.limits.items[{index}]"
    table = as_table(raw, name)
    named = table.get("name_pattern")
    texts = (
        names(table, "text_patterns", name, allow_empty=True) if "text_patterns" in table else ()
    )
    if named is None and not texts:
        raise ValueError(f"{name} needs a name_pattern or text_patterns")
    return LimitSpec(
        key=require_str(table, "key", name).strip(),
        programme=require_str(table, "programme", name).strip(),
        heading=names(table, "heading", name, allow_empty=False),
        name_pattern=re.compile(require_str(table, "name_pattern", name)) if named else None,
        text_patterns=tuple(_pattern(t, f"{name}.text_patterns") for t in texts),
    )


def _units(table: dict[str, object]) -> Mapping[str, str]:
    name = f"{_NAME}.limits.units"
    block = subtable(table, "units", f"{_NAME}.limits")
    if not block:
        raise ValueError(f"{name} must not be empty")
    return {k.lower().replace(" ", ""): require_str(block, k, name).strip() for k in block}


def _limit_items(block: dict[str, object], name: str) -> tuple[LimitSpec, ...]:
    """The listed limits, each with a unique key."""
    raw = block.get("items")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{name}.items must be a non-empty list of tables")
    items = tuple(_limit(item, i) for i, item in enumerate(cast(list[object], raw)))
    if len({spec.key for spec in items}) != len(items):
        raise ValueError(f"{name}.items: keys must be unique")
    return items


def _limits(table: dict[str, object]) -> LimitsSettings:
    name = f"{_NAME}.limits"
    block = subtable(table, "limits", _NAME)
    items = _limit_items(block, name)
    priority = names(block, "twa_priority", name, allow_empty=False)
    if not set(priority) <= {spec.key for spec in items}:
        raise ValueError(f"{name}.twa_priority must name listed keys")
    molar_volume = require_number(block, "molar_volume_l_per_mol", minimum=1e-9, name=name)
    return LimitsSettings(
        molar_volume_l_per_mol=molar_volume,
        twa_priority=priority,
        units=_units(block),
        items=items,
    )


def _check_against_comptox(fields: tuple[FieldSpec, ...], path: Path | None) -> None:
    """Each field must be one CompTox fills, in the same unit (one unit per result field)."""
    comptox = load_comptox_settings(path)
    units = {spec.key: spec.target_unit for spec in comptox.properties}
    units[_WEIGHT_KEY] = comptox.molecular_weight.target_unit
    for spec in fields:
        expected = units.get(spec.key)
        if expected is None:
            raise ValueError(f"{_NAME}.fields: {spec.key!r} is not a numeric property result field")
        if expected != spec.target_unit:
            raise ValueError(
                f"{_NAME}.fields: {spec.key} target_unit {spec.target_unit!r} must equal "
                f"the CompTox one, {expected!r}",
            )


def load_pubchem_settings(path: Path | None = None) -> PubchemSettings:
    """Load and validate the PubChem settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    fields = _fields(table)
    _check_against_comptox(fields, path)
    return PubchemSettings(
        cid_by_smiles_url=_template(table, "cid_by_smiles_url", "smiles"),
        cid_by_name_url=_template(table, "cid_by_name_url", "name"),
        pug_view_url=_template(table, "pug_view_url", "cid"),
        user_agent=require_str(table, "user_agent", _NAME).strip(),
        delay_seconds=_delay(table),
        timeout_seconds=require_number(table, "timeout_seconds", minimum=0.001, name=_NAME),
        max_retries=require_int(table, "max_retries", minimum=0, name=_NAME),
        backoff_seconds=require_number(table, "backoff_seconds", minimum=0, name=_NAME),
        cas_heading=names(table, "cas_heading", _NAME, allow_empty=False),
        agreement_ratio=_ratio(table),
        cache=_cache(subtable(table, "cache", _NAME)),
        fields=fields,
        limits=_limits(table),
    )


@lru_cache(maxsize=1)
def get_pubchem_settings() -> PubchemSettings:
    """Return the cached PubChem settings from the default file."""
    return load_pubchem_settings()
