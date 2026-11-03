"""Tier 1 stack candidates: read the sharded NEI stack table and bound its distinct stacks."""

from __future__ import annotations

import csv
import gzip
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from config.stack import STACK_QUANTITIES, NeiSettings, StackSettings
from tools.emissions.helpers.stack.stack_values import (
    StackRow,
    check_units_convertible,
    stack_values,
)

Stack = Mapping[str, float]
_Key = tuple[object, ...]
_SHARDS: dict[_Key, Mapping[str, tuple[StackRow, ...]]] = {}


@dataclass(frozen=True)
class Candidates:
    """Distinct stack combinations of some EIS IDs, ready to report.

    Attributes:
        stacks: Returned combinations (m, m, m/s, K), lowest stack first, at most the cap.
        total: Distinct combinations found before the cap.
        warnings: Notes on missing data, rejected rows, merging and omission.
    """

    stacks: tuple[Stack, ...]
    total: int
    warnings: tuple[str, ...]


def _check_header(header: Sequence[str] | None, nei: NeiSettings) -> None:
    wanted = [nei.id_column, *nei.columns.values()]
    missing = [name for name in wanted if name not in (header or [])]
    if missing:
        raise ValueError(f"NEI shard lacks configured columns: {', '.join(missing)}")


def _read_shard(path: Path, nei: NeiSettings) -> Mapping[str, tuple[StackRow, ...]]:
    """Read and index one shard; raises OSError, EOFError, csv.Error or UnicodeDecodeError."""
    by_id: dict[str, list[StackRow]] = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _check_header(reader.fieldnames, nei)
        for row in reader:
            by_id.setdefault((row[nei.id_column] or "").strip(), []).append(
                MappingProxyType(dict(row)),
            )
    return MappingProxyType({key: tuple(rows) for key, rows in by_id.items()})


def _cached_shard(path: Path, nei: NeiSettings) -> Mapping[str, tuple[StackRow, ...]]:
    """Return the indexed shard, read again only when the file or the settings change."""
    key: _Key = (path, path.stat().st_mtime_ns, nei.id_column, tuple(nei.columns.items()))
    if key not in _SHARDS:
        for stale in [k for k in _SHARDS if k[0] == path]:
            del _SHARDS[stale]
        _SHARDS[key] = _read_shard(path, nei)
    return _SHARDS[key]


def _rows_for(eis_ids: Sequence[str], nei: NeiSettings) -> tuple[list[StackRow], list[str]]:
    """Return the table rows of the EIS IDs and a warning per unreadable shard."""
    rows: list[StackRow] = []
    warnings: list[str] = []
    for eis_id in eis_ids:
        path = nei.shard_path(eis_id[: nei.prefix_digits])
        try:
            rows.extend(_cached_shard(path, nei).get(eis_id, ()))
        except (OSError, EOFError, csv.Error, UnicodeDecodeError) as exc:
            warnings.append(f"NEI file {path.name} could not be read ({exc.__class__.__name__})")
    return rows, warnings


def _valid_stacks(
    rows: Sequence[StackRow],
    nei: NeiSettings,
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> list[Stack]:
    """Convert each row to m, m, m/s and K; rows with any missing or implausible value drop."""
    stacks: list[Stack] = []
    for row in rows:
        values, _problems = stack_values(row, nei.columns, nei.units, settings, aliases)
        if values is not None:
            stacks.append(values)
    return stacks


def _merge(stacks: Sequence[Stack], digits: int) -> list[Stack]:
    """Keep the first of the stacks that are equal after rounding to ``digits`` digits."""
    kept: dict[tuple[float, ...], Stack] = {}
    for stack in stacks:
        key = tuple(float(f"{stack[q]:.{digits}g}") for q in STACK_QUANTITIES)
        kept.setdefault(key, stack)
    return list(kept.values())


def _lowest_first(stack: Stack) -> tuple[float, float, float, float]:
    return (
        stack["stack_height"],
        stack["exit_velocity"],
        stack["exit_temperature"],
        stack["stack_diameter"],
    )


def _notes(rejected: int, valid: int, total: int, kept: int) -> list[str]:
    notes: list[str] = []
    if rejected:
        notes.append(
            f"{rejected} NEI stack row(s) were ignored: a value was missing or implausible",
        )
    merged = valid - total
    if merged or total > kept:
        notes.append(
            f"{total} distinct stack combinations found ({merged} near-identical merged); "
            f"the {kept} lowest stacks are returned, {total - kept} taller omitted",
        )
    return notes


def build_candidates(
    eis_ids: Sequence[str],
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> Candidates:
    """Find the distinct stack combinations of the EIS IDs, merged, ordered and capped.

    Args:
        eis_ids: EIS facility IDs as digit strings.
        settings: NEI table location, reported units, cap, merge precision, ranges.
        aliases: Unit spelling -> Pint-parsable unit string.

    Returns:
        Up to ``max_candidates`` combinations in m, m, m/s and K, lowest stack first (ties:
        lowest exit velocity, exit temperature, diameter). Combinations are real rows, never
        averaged; rows with any missing or implausible value are dropped. Problems are
        reported in ``warnings``; data problems never raise.

    Raises:
        ValueError: If the configuration is unusable (unconvertible unit, missing column).
    """
    nei = settings.nei
    check_units_convertible(nei.units, settings, aliases)
    rows, warnings = _rows_for(eis_ids, nei)
    valid = _valid_stacks(rows, nei, settings, aliases)
    merged = sorted(_merge(valid, nei.merge_significant_digits), key=_lowest_first)
    kept = merged[: nei.max_candidates]
    if not rows and not warnings:
        warnings.append(f"the NEI table has no stack data for EIS ID {', '.join(eis_ids)}")
    warnings += _notes(len(rows) - len(valid), len(valid), len(merged), len(kept))
    return Candidates(tuple(kept), len(merged), tuple(warnings))
