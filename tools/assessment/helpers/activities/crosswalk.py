"""The bundled crosswalk of CDR industrial sector and life cycle stage to generic scenarios.

Each row names the EPA generic scenario or OECD emission scenario document that describes the
worker activities of an industry at one TSCA life cycle stage, and the catalogue activities it
describes. The file is read once and validated: an unknown activity, a stage outside the three, or
a malformed row is an error that names its line. A row adds activities; it never removes one.
"""

from __future__ import annotations

import csv
from collections.abc import Collection
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.generic_scenarios import get_generic_scenario_settings
from config.occupational import get_occupational_settings
from config.occupational_activities import STAGES

COLUMNS = ("is_code", "lifecycle_stage", "scenario", "category", "activities", "pages", "source")


@dataclass(frozen=True)
class ScenarioRow:
    """One row of the crosswalk.

    Attributes:
        line: Line number in the file (for messages).
        is_code: CDR industrial sector code, e.g. "IS13".
        stage: TSCA life cycle stage.
        scenario: Title of the generic scenario or emission scenario document.
        category: Kind of document (published ESD, draft ESD, ...).
        activities: Catalogue activity keys the document describes, in file order.
        pages: Where the document describes each activity.
        source: The document's citation.
    """

    line: int
    is_code: str
    stage: str
    scenario: str
    category: str
    activities: tuple[str, ...]
    pages: str
    source: str


@dataclass(frozen=True)
class Crosswalk:
    """The validated rows (immutable)."""

    rows: tuple[ScenarioRow, ...]

    def rows_for(self, is_code: str, stage: str) -> tuple[ScenarioRow, ...]:
        """The rows of a sector and stage, in file order."""
        return tuple(r for r in self.rows if r.is_code == is_code and r.stage == stage)


def _lines(path: Path) -> list[tuple[int, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        numbered = enumerate(handle, start=1)
        return [(n, text) for n, text in numbered if text.strip() and not text.startswith("#")]


def _fields(number: int, text: str, header: list[str]) -> dict[str, str]:
    values = next(csv.reader([text]))
    if len(values) != len(header):
        raise ValueError(
            f"crosswalk line {number}: expected {len(header)} columns, got {len(values)}",
        )
    return dict(zip(header, (v.strip() for v in values), strict=True))


def _check_fields(number: int, record: dict[str, str]) -> None:
    blank = [c for c in COLUMNS if not record.get(c)]
    if blank:
        raise ValueError(f"crosswalk line {number}: {blank[0]} is empty")
    if record["lifecycle_stage"] not in STAGES:
        stage = record["lifecycle_stage"]
        raise ValueError(f"crosswalk line {number}: unknown life cycle stage {stage!r}")


def _activities(number: int, record: dict[str, str], known: Collection[str]) -> tuple[str, ...]:
    activities = tuple(a.strip() for a in record["activities"].split(";") if a.strip())
    unknown = [a for a in activities if a not in known]
    if unknown or not activities:
        raise ValueError(f"crosswalk line {number}: unknown activity {(unknown or [''])[0]!r}")
    return activities


def _row(number: int, record: dict[str, str], known: Collection[str]) -> ScenarioRow:
    _check_fields(number, record)
    return ScenarioRow(
        number,
        record["is_code"],
        record["lifecycle_stage"],
        record["scenario"],
        record["category"],
        _activities(number, record, known),
        record["pages"],
        record["source"],
    )


def read_crosswalk(path: Path, known_activities: Collection[str]) -> Crosswalk:
    """Read and validate the crosswalk file.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a row is malformed, names an unknown activity or a stage outside
            Manufacturing, Processing and Industrial use; the message names the line.
    """
    lines = _lines(path)
    if not lines:
        raise ValueError(f"crosswalk {path.name} has no header")
    header = [h.strip() for h in next(csv.reader([lines[0][1]]))]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ValueError(f"crosswalk {path.name}: missing column {missing[0]}")
    rows = tuple(_row(n, _fields(n, text, header), known_activities) for n, text in lines[1:])
    return Crosswalk(rows)


@lru_cache(maxsize=4)
def _cached(path: Path, known: frozenset[str]) -> Crosswalk:
    return read_crosswalk(path, known)


def get_crosswalk() -> Crosswalk:
    """The configured crosswalk, read once and then reused (it is immutable)."""
    known = frozenset(get_occupational_settings().activities)
    return _cached(get_generic_scenario_settings().crosswalk_path, known)
