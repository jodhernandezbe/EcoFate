"""The read-across catalog: TRI chemicals with their structures, embeddings and fingerprints.

Read once per process from the parquet shards the builder writes, validated on load (a bad
catalog is a setup error and raises), and held as read-only NumPy matrices so a query is
scored against every chemical in one vectorized step.

The file stores the model's own (uncentered) embeddings. The isotropy correction is applied
here, on load: the catalog's mean embedding is computed once and the rows are centred on it,
so the correction can change without rebuilding the file.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

from config.read_across import CatalogColumns, ReadAcrossSettings
from models.chemistry.similarity import centered, mean_vector

BUILD_COMMAND = "uv run python -m scripts.build_tri_embeddings"
_MIN_CHEMICALS = 2  # a one-chemical catalog is its own mean, so it cannot be centred
_VECTOR_TYPE = "float32"  # the stored embedding element type
_BIT_TYPE = "int8"  # the stored fingerprint element type (values 0 and 1)
_COMPRESSION = "zstd"
SOURCE_TRI_LIST = "tri_list"  # a chemical TRI lists on its own
SOURCE_TRI_CATEGORY = "tri_category"  # an organic member of a TRI category

type Columns = dict[str, list[object]]


@dataclass(frozen=True)
class Catalog:
    """Candidate surrogates, one row per chemical; every array is read-only.

    Attributes:
        cas: Hyphenated CAS numbers.
        names: Chemical names.
        smiles: Canonical SMILES.
        molecular_weights: Molecular weights in g/mol, shape (N,).
        embeddings: The model's own L2-normalized embeddings, shape (N, width), float32,
            exactly as stored (not centred).
        mean_embedding: Mean of the *whole* catalog's embeddings, shape (width,). Filtering
            never changes it, so a filter narrows the candidates without moving any score.
        centered_embeddings: ``embeddings`` centred on ``mean_embedding`` and re-normalized,
            shape (N, width). This is what a query is compared against.
        bits: Morgan fingerprint bits (0/1), shape (N, n_bits), uint8.
        benchmark_flags: Whether each chemical has an IRIS benchmark, or None if the catalog
            has no such column.
        naics_prefixes: NAICS prefixes each chemical is reported under, or None if the
            catalog has no such column.
        sources: Where each row came from ("tri_list" or "tri_category"), or None if the
            catalog has no such column.
        category_codes: TRI category codes each chemical is reported under (empty for a
            chemical of the TRI list), or None if the catalog has no such column.
        category_names: Names of those categories, in the same order, or None likewise.
    """

    cas: tuple[str, ...]
    names: tuple[str, ...]
    smiles: tuple[str, ...]
    molecular_weights: NDArray[np.float64]
    embeddings: NDArray[np.float32]
    mean_embedding: NDArray[np.float64]
    centered_embeddings: NDArray[np.float64]
    bits: NDArray[np.uint8]
    benchmark_flags: NDArray[np.bool_] | None
    naics_prefixes: tuple[tuple[str, ...], ...] | None
    sources: tuple[str, ...] | None
    category_codes: tuple[tuple[str, ...], ...] | None
    category_names: tuple[tuple[str, ...], ...] | None

    def __len__(self) -> int:
        """Number of chemicals."""
        return len(self.cas)

    def index_of(self, cas: str) -> int | None:
        """Row of ``cas``, or None if it is not in the catalog."""
        return self.cas.index(cas) if cas in self.cas else None

    def subset(self, keep: NDArray[np.bool_]) -> Catalog:
        """Return the rows where ``keep`` is True (new read-only arrays)."""
        rows = [i for i, kept in enumerate(keep.tolist()) if kept]
        flags = self.benchmark_flags
        return Catalog(
            cas=tuple(self.cas[i] for i in rows),
            names=tuple(self.names[i] for i in rows),
            smiles=tuple(self.smiles[i] for i in rows),
            molecular_weights=_frozen(self.molecular_weights[keep]),
            embeddings=_frozen(self.embeddings[keep]),
            mean_embedding=self.mean_embedding,  # the whole catalog's mean, never the subset's
            centered_embeddings=_frozen(self.centered_embeddings[keep]),
            bits=_frozen(self.bits[keep]),
            benchmark_flags=None if flags is None else _frozen(flags[keep]),
            naics_prefixes=_pick(self.naics_prefixes, rows),
            sources=_pick(self.sources, rows),
            category_codes=_pick(self.category_codes, rows),
            category_names=_pick(self.category_names, rows),
        )

    def category_of(self, row: int) -> tuple[str, str] | None:
        """The first TRI category (code, name) row ``row`` is reported under, if any."""
        if self.category_codes is None or self.category_names is None:
            return None
        codes, names = self.category_codes[row], self.category_names[row]
        return (codes[0], names[0]) if codes and names else None


def _pick[T](values: tuple[T, ...] | None, rows: list[int]) -> tuple[T, ...] | None:
    return None if values is None else tuple(values[i] for i in rows)


def _frozen[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    array.flags.writeable = False
    return array


def read_columns(path: Path) -> Columns:
    """Read one parquet file as column name -> list of row values (pyarrow is untyped)."""
    table = pq.read_table(str(path))  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return cast(Columns, table.to_pydict())  # pyright: ignore[reportUnknownMemberType]


def _list_array(values: list[object], element: str) -> object:
    """A pyarrow list array of ``element`` (pyarrow is untyped, so this is the one wrapper)."""
    item = pa.type_for_alias(element)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return cast(object, pa.array(values, type=pa.list_(item)))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def write_columns(columns: Columns, path: Path, catalog: CatalogColumns) -> None:
    """Write one shard: vectors as float32, bits as int8, zstd-compressed.

    float64 vectors and int64 bits make the catalog several times larger for precision the
    similarity scores do not carry.
    """
    typed: dict[str, object] = dict(columns)
    for name, element in ((catalog.embedding, _VECTOR_TYPE), (catalog.bits, _BIT_TYPE)):
        if name in typed:
            typed[name] = _list_array(columns[name], element)
    for name in (catalog.category_codes, catalog.category_names):
        if name in typed:
            typed[name] = _list_array(columns[name], "string")  # empty lists stay list<string>
    table = pa.table(typed)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    pq.write_table(  # pyright: ignore[reportUnknownMemberType]
        table,  # pyright: ignore[reportUnknownArgumentType]
        str(path),
        compression=_COMPRESSION,
    )


def read_shards(settings: ReadAcrossSettings) -> Columns:
    """Read every catalog shard and concatenate them, in shard-prefix order.

    Raises:
        FileNotFoundError: If the directory holds no shard (the message gives the build
            command).
        ValueError: If the shards do not all carry the same columns.
    """
    paths = settings.shard_paths()
    if not paths:
        raise FileNotFoundError(
            f"read-across catalog not found in {settings.directory}; "
            f"build it with: {BUILD_COMMAND}",
        )
    merged: Columns = {}
    for path in paths:
        shard = read_columns(path)
        if merged and set(shard) != set(merged):
            raise ValueError(f"read-across catalog shard {path} has different columns")
        for name, values in shard.items():
            merged.setdefault(name, []).extend(values)
    return merged


class _Reader:
    """Validates one catalog file's columns; every error names the file and the column."""

    def __init__(self, columns: Columns, path: Path) -> None:
        self._columns = columns
        self._path = path

    def fail(self, column: str, problem: str) -> ValueError:
        return ValueError(f"read-across catalog {self._path}: column {column!r} {problem}")

    def column(self, name: str) -> list[object]:
        if name not in self._columns:
            raise self.fail(name, "is missing")
        return self._columns[name]

    def strings(self, name: str) -> tuple[str, ...]:
        values = self.column(name)
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise self.fail(name, "must hold non-empty text")
        return tuple(cast(str, v).strip() for v in values)

    def weights(self, name: str) -> NDArray[np.float64]:
        values = self.column(name)
        ok = all(
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v > 0
            for v in values
        )
        if not ok:
            raise self.fail(name, "must hold finite numbers greater than zero")
        return _frozen(np.asarray(values, dtype=np.float64))

    def matrix(self, name: str, width: int) -> NDArray[np.float64]:
        values = self.column(name)
        try:
            array = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise self.fail(name, f"must hold lists of {width} numbers") from exc
        if array.shape != (len(values), width) or not bool(np.all(np.isfinite(array))):
            raise self.fail(name, f"must hold lists of {width} finite numbers")
        return array

    def bits(self, name: str, width: int) -> NDArray[np.uint8]:
        array = self.matrix(name, width)
        if not bool(np.all((array == 0) | (array == 1))):
            raise self.fail(name, "must hold only 0 and 1")
        return _frozen(array.astype(np.uint8))

    def flags(self, name: str) -> NDArray[np.bool_] | None:
        if name not in self._columns:
            return None
        values = self._columns[name]
        if not all(isinstance(v, bool) for v in values):
            raise self.fail(name, "must hold true or false")
        return _frozen(np.asarray(values, dtype=np.bool_))

    def optional_strings(self, name: str) -> tuple[str, ...] | None:
        return self.strings(name) if name in self._columns else None

    def prefixes(self, name: str) -> tuple[tuple[str, ...], ...] | None:
        if name not in self._columns:
            return None
        rows = self._columns[name]
        if not all(_is_text_list(row) for row in rows):
            raise self.fail(name, "must hold lists of text")
        return tuple(tuple(str(p).strip() for p in cast(list[object], row or [])) for row in rows)


def _is_text_list(row: object) -> bool:
    if row is None:
        return True
    return isinstance(row, list) and all(isinstance(p, str) for p in cast(list[object], row))


def _unique(cas: Sequence[str], reader: _Reader, column: str) -> None:
    if len(set(cas)) != len(cas):
        raise reader.fail(column, "has a repeated CAS number")


def _corrected(
    embeddings: NDArray[np.float64],
    reader: _Reader,
    column: str,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The catalog's mean embedding and its centred, re-normalized rows (isotropy correction).

    A stored row sitting exactly at the mean would have no direction once centred; that is a
    broken catalog, so it raises rather than scoring arbitrarily.
    """
    mean = mean_vector(embeddings)
    try:
        return mean, _frozen(centered(embeddings, mean))
    except ValueError as exc:
        raise reader.fail(column, f"cannot be centred: {exc}") from exc


Identity = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]


def _identity(reader: _Reader, columns: CatalogColumns) -> Identity:
    """The CAS numbers, names and SMILES, checked for size and duplicates."""
    cas = reader.strings(columns.cas)
    if len(cas) < _MIN_CHEMICALS:
        raise reader.fail(
            columns.cas,
            f"has {len(cas)} chemicals; at least {_MIN_CHEMICALS} are needed, because the "
            "isotropy correction measures each one against the catalog's mean embedding",
        )
    _unique(cas, reader, columns.cas)
    return cas, reader.strings(columns.name), reader.strings(columns.smiles)


def _build(reader: _Reader, columns: CatalogColumns, settings: ReadAcrossSettings) -> Catalog:
    cas, names, smiles = _identity(reader, columns)
    embeddings = reader.matrix(columns.embedding, settings.model.embedding_width)
    mean, corrected = _corrected(embeddings, reader, columns.embedding)
    return Catalog(
        cas=cas,
        names=names,
        smiles=smiles,
        molecular_weights=reader.weights(columns.molecular_weight),
        embeddings=_frozen(embeddings.astype(np.float32)),
        mean_embedding=_frozen(mean),
        centered_embeddings=corrected,
        bits=reader.bits(columns.bits, settings.fingerprint.n_bits),
        benchmark_flags=reader.flags(columns.benchmark_flag),
        naics_prefixes=reader.prefixes(columns.naics_prefixes),
        sources=reader.optional_strings(columns.source),
        category_codes=reader.prefixes(columns.category_codes),
        category_names=reader.prefixes(columns.category_names),
    )


def load_catalog(settings: ReadAcrossSettings) -> Catalog:
    """Read and validate every catalog shard as one catalog.

    Args:
        settings: Shard location, column names and expected embedding and fingerprint widths.

    Raises:
        FileNotFoundError: If no shard exists (the message gives the build command).
        ValueError: If a column is missing or malformed, or the catalog holds fewer than two
            chemicals; the message names the location and the column.
    """
    reader = _Reader(read_shards(settings), settings.directory)
    return _build(reader, settings.columns, settings)


@lru_cache(maxsize=1)
def get_catalog(settings: ReadAcrossSettings) -> Catalog:
    """Return the configured catalog, read once per process."""
    return load_catalog(settings)


def _naics_mask(catalog: Catalog, prefix: str) -> NDArray[np.bool_] | None:
    rows = catalog.naics_prefixes
    if rows is None:
        return None
    return np.asarray([any(code.startswith(prefix) for code in row) for row in rows])


def _narrow(
    catalog: Catalog,
    keep: NDArray[np.bool_] | None,
    label: str,
    warnings: list[str],
) -> Catalog:
    """Apply ``keep``; when it is missing or keeps nothing, warn and keep every row."""
    if keep is None:
        warnings.append(f"{label} filter not applied: the catalog has no column for it")
        return catalog
    if not bool(keep.any()):
        warnings.append(f"{label} filter matched no chemical; all candidates were used")
        return catalog
    return catalog.subset(keep)


def filter_candidates(
    catalog: Catalog,
    *,
    require_benchmarks: bool,
    naics_prefix: str | None,
) -> tuple[Catalog, list[str]]:
    """Narrow the candidate surrogates.

    Args:
        catalog: All catalog chemicals.
        require_benchmarks: Keep only chemicals flagged as having an IRIS benchmark.
        naics_prefix: Keep only chemicals reported under a NAICS code with this prefix.

    Returns:
        The candidates and one warning per filter that could not be applied or fell back to
        all candidates (a missing column, or no chemical matching).
    """
    warnings: list[str] = []
    candidates = catalog
    if require_benchmarks:
        candidates = _narrow(candidates, candidates.benchmark_flags, "benchmark", warnings)
    prefix = (naics_prefix or "").strip()
    if prefix:
        keep = _naics_mask(candidates, prefix)
        candidates = _narrow(candidates, keep, f"NAICS {prefix!r}", warnings)
    return candidates, warnings
