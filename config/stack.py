"""Typed loader for the ``[stack]`` settings (stack-parameter tools)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import cast

from config.parsing import (
    project_path,
    read_toml,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)

_MAX_SIGNIFICANT_DIGITS = 15  # float64 carries about 15 to 17
STACK_QUANTITIES = ("stack_height", "stack_diameter", "exit_velocity", "exit_temperature")


@dataclass(frozen=True)
class StackRange:
    """Plausible inclusive range of one stack quantity, in its target unit."""

    minimum: float
    maximum: float


@dataclass(frozen=True)
class PstkSettings:
    """Where and how the PSTK (Point Source Stack Replacements) file is read.

    Attributes:
        path: CSV file, absolute or resolved against the project root.
        scc_column: Column holding the SCC.
        fips_column: Column holding the FIPS code, or None to treat every row as national.
        national_fips: FIPS values (besides an empty cell) that mark national default rows.
        columns: Quantity (see ``STACK_QUANTITIES``) -> column name.
        units: Quantity -> unit the file reports it in, e.g. ``"ft"``.
    """

    path: Path
    scc_column: str
    fips_column: str | None
    national_fips: tuple[str, ...]
    columns: Mapping[str, str]
    units: Mapping[str, str]


@dataclass(frozen=True)
class NeiSettings:
    """Where and how the compact NEI stack table is read and built.

    Attributes:
        directory: Folder of shard files, absolute or resolved against the project root.
        file_template: Shard file name; ``{prefix}`` is the leading digits of the EIS ID.
        prefix_digits: Number of leading EIS ID digits that name a shard.
        id_column: Shard column holding the EIS facility ID.
        columns: Quantity (see ``STACK_QUANTITIES``) -> shard column name.
        units: Quantity -> unit the shards report it in, e.g. ``"ft"``.
        max_candidates: Most distinct stack combinations returned for a facility.
        merge_significant_digits: Combinations equal after rounding every value to this many
            significant digits are merged into one.
        raw_path: Raw NEI SMOKE flat file (zip) the shards are built from.
        raw_id_column: Raw file column holding the EIS facility ID.
        raw_columns: Quantity -> raw file column name.
    """

    directory: Path
    file_template: str
    prefix_digits: int
    id_column: str
    columns: Mapping[str, str]
    units: Mapping[str, str]
    max_candidates: int
    merge_significant_digits: int
    raw_path: Path
    raw_id_column: str
    raw_columns: Mapping[str, str]

    def shard_path(self, prefix: str) -> Path:
        """Return the shard file for an EIS ID prefix."""
        return self.directory / self.file_template.format(prefix=prefix)


@dataclass(frozen=True)
class StackSettings:
    """Stack-parameter settings.

    Attributes:
        pstk: PSTK file settings (tier 2).
        nei: NEI stack table settings (tier 1).
        target_units: Quantity -> unit the tools return: m, m, m/s and K.
        ranges: Quantity -> plausible range in the target unit; values outside are rejected.
        global_fallback: Quantity -> AirToxScreen global point-source default, target unit.
    """

    pstk: PstkSettings
    nei: NeiSettings
    target_units: Mapping[str, str]
    ranges: Mapping[str, StackRange]
    global_fallback: Mapping[str, float]


def _per_quantity[T](
    table: dict[str, object],
    name: str,
    parse: Callable[[dict[str, object], str, str], T],
) -> Mapping[str, T]:
    """Parse a table that must hold exactly one entry per stack quantity."""
    unknown = sorted(set(table) - set(STACK_QUANTITIES))
    if unknown:
        raise ValueError(f"{name} has unknown quantities: {', '.join(unknown)}")
    return MappingProxyType({q: parse(table, q, name) for q in STACK_QUANTITIES})


def _positive(table: dict[str, object], key: str, name: str) -> float:
    return require_number(table, key, minimum=1e-12, name=name)


def _range(table: dict[str, object], key: str, name: str) -> StackRange:
    raw = table.get(key)
    if not isinstance(raw, list) or len(cast(list[object], raw)) != 2:
        raise ValueError(f"{name}.{key} must be [minimum, maximum]")
    bounds = {"minimum": cast(list[object], raw)[0], "maximum": cast(list[object], raw)[1]}
    low = _positive(bounds, "minimum", f"{name}.{key}")
    high = _positive(bounds, "maximum", f"{name}.{key}")
    if low >= high:
        raise ValueError(f"{name}.{key} minimum must be below maximum")
    return StackRange(minimum=low, maximum=high)


def _fips_values(table: dict[str, object]) -> tuple[str, ...]:
    raw = table.get("national_fips", [])
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in cast(list[object], raw)):
        raise ValueError("stack.pstk.national_fips must be a list of strings")
    return tuple(v.strip() for v in cast(list[str], raw))


def _optional_column(table: dict[str, object], key: str) -> str | None:
    return require_str(table, key, "stack.pstk").strip() if key in table else None


def _parse_pstk(stack: dict[str, object]) -> PstkSettings:
    table = subtable(stack, "pstk", "stack")
    name = "stack.pstk"
    return PstkSettings(
        path=project_path(table, "path", name),
        scc_column=require_str(table, "scc_column", name).strip(),
        fips_column=_optional_column(table, "fips_column"),
        national_fips=_fips_values(table),
        columns=_per_quantity(subtable(table, "columns", name), f"{name}.columns", require_str),
        units=_per_quantity(subtable(table, "units", name), f"{name}.units", require_str),
    )


def _merge_digits(table: dict[str, object]) -> int:
    digits = require_number(table, "merge_significant_digits", minimum=1, name="stack.nei")
    if digits > _MAX_SIGNIFICANT_DIGITS or digits != int(digits):
        raise ValueError(
            f"stack.nei.merge_significant_digits must be 1 to {_MAX_SIGNIFICANT_DIGITS}",
        )
    return int(digits)


def _file_template(table: dict[str, object]) -> str:
    template = require_str(table, "file_template", "stack.nei")
    if "{prefix}" not in template:
        raise ValueError("stack.nei.file_template must contain {prefix}")
    return template


def _nei_names(table: dict[str, object], name: str, key: str) -> Mapping[str, str]:
    """One string per quantity from the ``[stack.nei.<key>]`` subtable."""
    return _per_quantity(subtable(table, key, name), f"{name}.{key}", require_str)


def _parse_nei(stack: dict[str, object]) -> NeiSettings:
    table = subtable(stack, "nei", "stack")
    name = "stack.nei"
    return NeiSettings(
        directory=project_path(table, "directory", name),
        file_template=_file_template(table),
        prefix_digits=require_int(table, "prefix_digits", minimum=1, name=name),
        id_column=require_str(table, "id_column", name).strip(),
        columns=_nei_names(table, name, "columns"),
        units=_nei_names(table, name, "units"),
        max_candidates=require_int(table, "max_candidates", minimum=1, name=name),
        merge_significant_digits=_merge_digits(table),
        raw_path=project_path(table, "raw_path", name),
        raw_id_column=require_str(table, "raw_id_column", name).strip(),
        raw_columns=_nei_names(table, name, "raw_columns"),
    )


def _check_fallback_in_range(settings: StackSettings) -> None:
    for quantity, value in settings.global_fallback.items():
        bounds = settings.ranges[quantity]
        if not bounds.minimum <= value <= bounds.maximum:
            raise ValueError(f"stack.global_fallback.{quantity} lies outside stack.ranges")


def load_stack_settings(path: Path | None = None) -> StackSettings:
    """Load and validate the stack-parameter settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (ranges and fallback values in the target units).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    stack = section(read_toml(path), "stack")
    settings = StackSettings(
        pstk=_parse_pstk(stack),
        nei=_parse_nei(stack),
        target_units=_per_quantity(
            subtable(stack, "target_units", "stack"),
            "stack.target_units",
            require_str,
        ),
        ranges=_per_quantity(subtable(stack, "ranges", "stack"), "stack.ranges", _range),
        global_fallback=_per_quantity(
            subtable(stack, "global_fallback", "stack"),
            "stack.global_fallback",
            _positive,
        ),
    )
    _check_fallback_in_range(settings)
    return settings


@lru_cache(maxsize=1)
def get_stack_settings() -> StackSettings:
    """Return the cached stack settings from the default file."""
    return load_stack_settings()
