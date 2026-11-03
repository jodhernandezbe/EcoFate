"""Read the question catalogue: one row per question, validated once at the boundary."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

COLUMNS = ("question", "category", "type")
TYPES = frozenset({"happy_path", "varied_phrasing", "edge_case", "out_of_scope", "breaking"})


@dataclass(frozen=True)
class CatalogueRow:
    """One catalogue question.

    Attributes:
        question: The user message sent to the agent, verbatim.
        category: Short label of the rule or step the question tests.
        type: One of ``TYPES``.
    """

    question: str
    category: str
    type: str


def read_rows(text: str) -> tuple[CatalogueRow, ...]:
    """Parse catalogue CSV text.

    Raises:
        ValueError: On a wrong header, a row with the wrong number of cells, an empty cell or
            an unknown type; the message names the line (the header is line 1).
    """
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(f"catalogue header must be {','.join(COLUMNS)}")
    return tuple(_row(raw, line) for line, raw in enumerate(reader, start=2))


def _row(raw: Mapping[str | None, str | None], line: int) -> CatalogueRow:
    if None in raw or None in raw.values():  # an extra cell, or a missing one
        raise ValueError(f"catalogue line {line}: expected {len(COLUMNS)} cells")
    cells = {column: (raw.get(column) or "").strip() for column in COLUMNS}
    for column, value in cells.items():
        if not value:
            raise ValueError(f"catalogue line {line}: empty {column}")
    if cells["type"] not in TYPES:
        raise ValueError(f"catalogue line {line}: unknown type {cells['type']!r}")
    return CatalogueRow(cells["question"], cells["category"], cells["type"])


def load_catalogue(path: Path) -> tuple[CatalogueRow, ...]:
    """Read and validate the catalogue file at ``path``."""
    return read_rows(path.read_text(encoding="utf-8"))
