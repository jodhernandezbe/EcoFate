"""The question catalogue ``evals/scenarios.csv`` keeps the shape the harness relies on."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "evals" / "scenarios.csv"
COLUMNS = ("question", "category", "type")
TYPES = frozenset({"happy_path", "varied_phrasing", "edge_case", "out_of_scope", "breaking"})
MIN_ROWS = 50
MIN_BREAKING = 5


def _rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    assert tuple(reader.fieldnames or ()) == COLUMNS, f"header must be {COLUMNS}"
    rows = list(reader)
    for number, row in enumerate(rows, start=2):
        assert None not in row and None not in row.values(), f"line {number}: wrong cell count"
        for column in COLUMNS:
            assert row[column].strip(), f"line {number}: empty {column}"
        assert row["type"] in TYPES, f"line {number}: unknown type {row['type']!r}"
    return rows


def _catalogue() -> list[dict[str, str]]:
    return _rows(CATALOGUE_PATH.read_text(encoding="utf-8"))


def test_catalogue_has_the_expected_header_and_no_empty_cells() -> None:
    _catalogue()


def test_catalogue_has_at_least_fifty_questions() -> None:
    assert len(_catalogue()) >= MIN_ROWS


def test_catalogue_has_at_least_five_breaking_questions() -> None:
    breaking = [r for r in _catalogue() if r["type"] == "breaking"]
    assert len(breaking) >= MIN_BREAKING


def test_catalogue_covers_every_type() -> None:
    assert {r["type"] for r in _catalogue()} == TYPES


def test_catalogue_questions_are_unique() -> None:
    questions = [r["question"] for r in _catalogue()]
    assert len(set(questions)) == len(questions)


def test_missing_type_column_fails() -> None:
    with pytest.raises(AssertionError, match="header"):
        _rows("question,category\nAssess CAS 71-43-2.,full-assessment-cas\n")


def test_unknown_type_value_fails() -> None:
    with pytest.raises(AssertionError, match="unknown type"):
        _rows("question,category,type\nAssess CAS 71-43-2.,full-assessment-cas,smoke\n")


def test_empty_question_fails() -> None:
    with pytest.raises(AssertionError, match="empty question"):
        _rows("question,category,type\n,full-assessment-cas,happy_path\n")


def test_extra_cell_fails() -> None:
    with pytest.raises(AssertionError, match="cell count"):
        _rows("question,category,type\nAssess CAS 71-43-2.,full-assessment-cas,happy_path,x\n")
