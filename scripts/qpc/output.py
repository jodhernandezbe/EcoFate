"""Write the baseline parquet: one row per four-digit code, release recorded, atomically."""

# pyarrow ships no type information, so strict mode cannot see through its objects here.
# pyright: reportUnknownVariableType=false, reportUnknownParameterType=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.qpc.release import Release
from scripts.qpc.table import Extraction

SCHEMA = pa.schema(
    [
        ("naics_code", pa.string()),
        ("avg_plant_hours_per_week", pa.float64()),
        ("source_naics", pa.string()),
        ("source_title", pa.string()),
        ("release_year", pa.int16()),
        ("release_quarter", pa.int8()),
    ],
)


@dataclass(frozen=True)
class Provenance:
    """Where the file came from; stored in the parquet's metadata."""

    url: str
    sha256: str
    retrieved: str
    naics_edition: int
    sheet: str


def build_table(extraction: Extraction, release: Release, provenance: Provenance) -> pa.Table:
    """The Arrow table, sorted by code, with the release in its metadata."""
    rows = sorted(
        (code, e.hours, e.source_naics, e.source_title, release.year, release.quarter)
        for e in extraction.entries
        for code in e.codes
    )
    columns = list(zip(*rows, strict=True)) if rows else [[] for _ in SCHEMA]
    table = pa.Table.from_arrays(
        [pa.array(c, type=f.type) for c, f in zip(columns, SCHEMA, strict=True)],
        schema=SCHEMA,
    )
    meta = {
        "qpc.release": release.label,
        "qpc.url": provenance.url,
        "qpc.sha256": provenance.sha256,
        "qpc.retrieved": provenance.retrieved,
        "qpc.naics_edition": str(provenance.naics_edition),
        "qpc.sheet": provenance.sheet,
    }
    return table.replace_schema_metadata(meta)


def write_atomic(table: pa.Table, path: Path) -> None:
    """Write ``table`` to ``path`` through a temp file in the same folder (all or nothing)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(handle)
    try:
        pq.write_table(table, name, compression="zstd", use_dictionary=False)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def write_baseline(
    extraction: Extraction,
    release: Release,
    provenance: Provenance,
    path: Path,
) -> None:
    """Build the table and write it to ``path``; the old file survives any failure."""
    write_atomic(build_table(extraction, release, provenance), path)


def read_rows(path: Path) -> list[dict[str, object]]:
    """The baseline's rows as dicts (column -> value), for checks and for consumers."""
    return cast(list[dict[str, object]], pq.read_table(path).to_pylist())


def read_metadata(path: Path) -> dict[str, str]:
    """The release information stored in the baseline's metadata."""
    raw = cast(dict[bytes, bytes] | None, pq.read_schema(path).metadata) or {}
    return {key.decode(): value.decode() for key, value in raw.items()}
