"""SCC documents: read, filter, dedupe and fingerprint the EPA SCC table."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TextIO

from config.retrieval import EmbeddingSettings, SccIndexSettings
from tools.emissions.rag.errors import SourceError
from tools.emissions.rag.vectorstore import IndexedDocument

SCC_TEXT_FIELDS = ("level_one", "level_two", "level_three", "level_four", "sector")
# Bump when the document text format changes, so persisted indexes are rebuilt.
_TEXT_VERSION = 1


@dataclass(frozen=True)
class SccDocument:
    """One Source Classification Code and its plain-text process description."""

    scc: str
    level_one: str
    level_two: str
    level_three: str
    level_four: str
    sector: str

    def text(self) -> str:
        """Text embedded for similarity search: all levels, broad to specific, and sector."""
        levels = " > ".join((self.level_one, self.level_two, self.level_three, self.level_four))
        return f"{levels} (sector: {self.sector})"

    def metadata(self) -> Mapping[str, str]:
        """Fields stored next to the vector, read back when the document is retrieved."""
        return MappingProxyType(
            {
                "level_one": self.level_one,
                "level_two": self.level_two,
                "level_three": self.level_three,
                "level_four": self.level_four,
                "sector": self.sector,
            },
        )

    @classmethod
    def from_metadata(cls, scc: str, metadata: Mapping[str, str]) -> SccDocument | None:
        """Rebuild a document from stored metadata; None if a field or level four is missing."""
        if any(field not in metadata for field in SCC_TEXT_FIELDS) or not metadata["level_four"]:
            return None
        return cls(
            scc=scc,
            level_one=metadata["level_one"],
            level_two=metadata["level_two"],
            level_three=metadata["level_three"],
            level_four=metadata["level_four"],
            sector=metadata["sector"],
        )

    def to_indexed(self) -> IndexedDocument:
        """The document as the vector index stores it (the SCC is its id)."""
        return IndexedDocument(id=self.scc, text=self.text(), metadata=self.metadata())


@dataclass(frozen=True)
class SccHit:
    """One retrieved SCC with its similarity score (0 unrelated to 1 identical)."""

    document: SccDocument
    score: float


def _cell(row: Mapping[str, str | None], column: str) -> str:
    return (row.get(column) or "").strip()


def _document(row: Mapping[str, str | None], columns: Mapping[str, str]) -> SccDocument | None:
    """Build a document from a table row; None without an SCC or a level four description."""
    scc, level_four = _cell(row, columns["scc"]), _cell(row, columns["level_four"])
    if not scc or not level_four:
        return None
    return SccDocument(
        scc=scc,
        level_one=_cell(row, columns["level_one"]),
        level_two=_cell(row, columns["level_two"]),
        level_three=_cell(row, columns["level_three"]),
        level_four=level_four,
        sector=_cell(row, columns["sector"]),
    )


def _wanted(row: Mapping[str, str | None], settings: SccIndexSettings) -> bool:
    columns = settings.columns
    return (
        _cell(row, columns["category"]) in settings.categories
        and _cell(row, columns["status"]) in settings.statuses
    )


def _collect(
    rows: Iterable[Mapping[str, str | None]],
    settings: SccIndexSettings,
) -> tuple[SccDocument, ...]:
    """Keep wanted rows with an SCC and level four; the first row of each SCC wins."""
    documents: dict[str, SccDocument] = {}
    for row in rows:
        document = _document(row, settings.columns) if _wanted(row, settings) else None
        if document is not None and document.scc not in documents:
            documents[document.scc] = document
    return tuple(documents.values())


def _check_columns(header: Sequence[str], settings: SccIndexSettings) -> None:
    """Raise ``ValueError`` when the table lacks a configured column (a setup error)."""
    missing = [column for column in settings.columns.values() if column not in header]
    if missing:
        source = settings.source_path
        raise ValueError(f"SCC table {source} lacks configured columns: {', '.join(missing)}")


def _open_table(path: Path) -> TextIO:
    """Open the table as text; a ``.gz`` file is decompressed on the fly."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8-sig")
    return path.open(newline="", encoding="utf-8-sig")


def load_documents(settings: SccIndexSettings) -> tuple[SccDocument, ...]:
    """Read the SCC table and return the documents to index, one per SCC.

    Args:
        settings: Table path, column mapping and the categories/statuses to keep.

    Returns:
        Documents in table order, deduplicated by SCC.

    Raises:
        SourceError: If the table cannot be read or no row passes the filters.
        ValueError: If the table lacks a configured column.
    """
    try:
        with _open_table(settings.source_path) as handle:
            reader = csv.DictReader(handle)
            _check_columns(list(reader.fieldnames or []), settings)
            documents = _collect(reader, settings)
    except (OSError, EOFError, csv.Error, UnicodeDecodeError) as exc:
        raise SourceError(f"SCC table {settings.source_path} could not be read: {exc}") from exc
    if not documents:
        raise SourceError("no SCC rows match the configured categories and statuses")
    return documents


def fingerprint(settings: SccIndexSettings, embedding: EmbeddingSettings) -> str:
    """Hash of the table bytes plus every setting that shapes the index.

    Raises:
        SourceError: If the table cannot be read.
    """
    try:
        digest = hashlib.sha256(settings.source_path.read_bytes())
    except OSError as exc:
        raise SourceError(f"SCC table {settings.source_path} could not be read: {exc}") from exc
    shape = {
        "categories": settings.categories,
        "statuses": settings.statuses,
        "columns": dict(settings.columns),
        "provider": embedding.provider,
        "model": embedding.model,
        "text_version": _TEXT_VERSION,
    }
    digest.update(json.dumps(shape, sort_keys=True).encode())
    return digest.hexdigest()
