"""The shipped catalogue keeps its shape, and the reader rejects a malformed one."""

from __future__ import annotations

import pytest

from config.evaluation import get_evaluation_settings
from evals.catalogue.rows import COLUMNS, TYPES, CatalogueRow, load_catalogue, read_rows

MIN_ROWS = 50
MIN_BREAKING = 5
HEADER = "question,category,type\n"


def _catalogue() -> tuple[CatalogueRow, ...]:
    return load_catalogue(get_evaluation_settings().catalogue)


def test_catalogue_has_at_least_fifty_questions() -> None:
    assert len(_catalogue()) >= MIN_ROWS


def test_catalogue_has_at_least_five_breaking_questions() -> None:
    assert sum(r.type == "breaking" for r in _catalogue()) >= MIN_BREAKING


def test_catalogue_covers_every_type() -> None:
    assert {r.type for r in _catalogue()} == TYPES


def test_catalogue_questions_are_unique() -> None:
    questions = [r.question for r in _catalogue()]
    assert len(set(questions)) == len(questions)


def test_row_fields_follow_the_columns() -> None:
    rows = read_rows(HEADER + "Assess CAS 71-43-2.,full-assessment-cas,happy_path\n")
    assert rows == (CatalogueRow("Assess CAS 71-43-2.", "full-assessment-cas", "happy_path"),)
    assert COLUMNS == ("question", "category", "type")


def test_quoted_question_with_commas_is_one_cell() -> None:
    rows = read_rows(HEADER + '"Assess CAS 71-43-2 in Houston, Texas.",scope,happy_path\n')
    assert rows[0].question == "Assess CAS 71-43-2 in Houston, Texas."


def test_missing_type_column_fails() -> None:
    with pytest.raises(ValueError, match="header"):
        read_rows("question,category\nAssess CAS 71-43-2.,full-assessment-cas\n")


def test_unknown_type_value_fails() -> None:
    with pytest.raises(ValueError, match="line 2: unknown type 'smoke'"):
        read_rows(HEADER + "Assess CAS 71-43-2.,full-assessment-cas,smoke\n")


def test_empty_question_fails() -> None:
    with pytest.raises(ValueError, match="line 2: empty question"):
        read_rows(HEADER + ",full-assessment-cas,happy_path\n")


def test_extra_cell_fails() -> None:
    with pytest.raises(ValueError, match="line 2: expected 3 cells"):
        read_rows(HEADER + "Assess CAS 71-43-2.,full-assessment-cas,happy_path,x\n")


def test_missing_cell_fails() -> None:
    with pytest.raises(ValueError, match="line 2: expected 3 cells"):
        read_rows(HEADER + "Assess CAS 71-43-2.,full-assessment-cas\n")


def test_problem_names_its_own_line() -> None:
    text = HEADER + "Assess CAS 71-43-2.,a,happy_path\nAssess CAS 50-00-0.,b,nope\n"
    with pytest.raises(ValueError, match="line 3"):
        read_rows(text)
