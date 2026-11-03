"""Tests for scripts.qpc.table (synthetic rows; values are placeholders, not Census data)."""

from __future__ import annotations

import dataclasses
import math

import pytest

from config.qpc import QpcSettings, get_qpc_settings
from scripts.qpc.errors import QpcDataError, QpcLayoutError
from scripts.qpc.release import Release
from scripts.qpc.table import Extraction, check_edition, extract, valid_hours
from scripts.qpc.workbook import Row
from tests.scripts.qpc.sheets import HEADER_ROWS, INTRO, data_row, sheet_rows

RELEASE = Release(2026, 2)
CHILDREN = {"313": ("3131", "3132")}


def _settings(**changes: int) -> QpcSettings:
    return dataclasses.replace(get_qpc_settings(), min_codes=1, **changes)


def _run(
    rows: list[Row],
    release: Release = RELEASE,
    settings: QpcSettings | None = None,
) -> Extraction:
    return extract(rows, release, settings or _settings(), CHILDREN)


def _reasons(result: Extraction) -> dict[str, str]:
    return {s.source_naics: s.reason for s in result.skipped}


def test_reads_the_requested_quarter_not_the_previous_one() -> None:
    result = _run(sheet_rows(data_row(3112, "Synthetic A", 11.0, previous=99.0)))
    assert [(e.codes, e.hours) for e in result.entries] == [(("3112",), 11.0)]


def test_previous_quarter_is_read_when_it_is_the_one_asked_for() -> None:
    rows = sheet_rows(data_row(3112, "Synthetic A", 11.0, previous=22.0))
    rows[0] = ("TABLE 1. Synthetic: 2026 Quarter 1",)
    assert _run(rows, Release(2026, 1)).entries[0].hours == 22.0


def test_group_three_digit_and_numeric_cells() -> None:
    rows = sheet_rows(
        data_row("3111,7,8", "Group", 12.5),
        data_row("313", "Textile-like", 33.0),
        data_row(3112, "Single", 44.0),
    )
    got = {c: e.hours for e in _run(rows).entries for c in e.codes}
    assert got == {
        "3111": 12.5,
        "3117": 12.5,
        "3118": 12.5,
        "3131": 33.0,
        "3132": 33.0,
        "3112": 44.0,
    }


def test_continuous_operation_is_kept() -> None:
    assert _run(sheet_rows(data_row("3252", "Continuous", 168))).entries[0].hours == 168.0


@pytest.mark.parametrize("bad", [0, -1, 169, math.nan, math.inf, True, "x", None])
def test_implausible_hours_are_skipped(bad: object) -> None:
    rows = sheet_rows(data_row("3252", "Bad", bad), data_row("3253", "Good", 10.0))  # type: ignore[arg-type]
    result = _run(rows)
    assert [e.codes for e in result.entries] == [("3253",)]
    assert "3252" in _reasons(result)


def test_withheld_is_reported() -> None:
    result = _run(sheet_rows(data_row(3122, "Withheld", "D"), data_row(3112, "Ok", 10.0)))
    assert _reasons(result) == {"3122": "estimate withheld (D)"}


def test_valid_hours_bounds_are_exclusive_low_inclusive_high() -> None:
    s = _settings()
    assert valid_hours(168, s) == 168.0
    assert valid_hours(0.1, s) == 0.1


def test_part_of_a_four_digit_code_leaves_it_absent() -> None:
    rows = sheet_rows(
        data_row("32411", "Refinery-like", 20.0),
        data_row("32412,9", "Asphalt-like", 21.0),
        data_row("3112", "Ok", 10.0),
    )
    result = _run(rows)
    assert [c for e in result.entries for c in e.codes] == ["3112"]
    assert set(_reasons(result)) == {"32411", "32412,9"}


def test_aggregate_row_is_reported() -> None:
    result = _run(sheet_rows(data_row("31-33 1/", "All", 10.0), data_row(3112, "Ok", 10.0)))
    assert "aggregate" in _reasons(result)["31-33"]


def test_overlapping_rows_are_both_removed() -> None:
    rows = sheet_rows(
        data_row("313", "Wide", 10.0),
        data_row("3131", "Narrow", 11.0),
        data_row(3112, "Ok", 12.0),
    )
    result = _run(rows)
    assert [c for e in result.entries for c in e.codes] == ["3112"]
    assert set(_reasons(result)) == {"313", "3131"}


def test_footnotes_below_the_table_are_ignored() -> None:
    notes = [
        (),
        ("  1/   Includes manufacturing plants.",),
        ("  D   Estimate withheld.",),
        ("Note: revised.",),
    ]
    result = _run([*sheet_rows(data_row(3112, "Ok", 10.0)), *notes])
    assert len(result.entries) == 1 and not result.skipped


def test_unparseable_code_with_hours_is_reported_not_dropped() -> None:
    result = _run(sheet_rows(data_row("??", "Odd", 10.0), data_row(3112, "Ok", 10.0)))
    assert "??" in _reasons(result)


def test_wrong_quarter_in_the_title() -> None:
    rows = sheet_rows(data_row(3112, "Ok", 10.0))
    rows[0] = ("TABLE 1. Synthetic: 2026 Quarter 3",)
    with pytest.raises(QpcLayoutError, match="asked for 2026Q2 but the sheet is 2026Q3"):
        _run(rows)


def test_wrong_year_in_the_title() -> None:
    rows = sheet_rows(data_row(3112, "Ok", 10.0))
    rows[0] = ("TABLE 1. Synthetic: 2025 Quarter 2",)
    with pytest.raises(QpcLayoutError, match="2025Q2"):
        _run(rows)


def test_block_year_must_match() -> None:
    rows = sheet_rows(data_row(3112, "Ok", 10.0))
    rows[2] = (None, None, None, 2025, None, None, None, 2025)
    with pytest.raises(QpcLayoutError, match="headed by year"):
        _run(rows)


def test_requested_quarter_missing_from_blocks() -> None:
    rows = sheet_rows(data_row(3112, "Ok", 10.0))
    rows[0] = ("TABLE 1. Synthetic: 2026 Quarter 4",)
    with pytest.raises(QpcLayoutError, match="quarters in the sheet are"):
        _run(rows, Release(2026, 4))


def test_hours_column_missing() -> None:
    rows = sheet_rows(data_row(3112, "Ok", 10.0))
    rows[4] = tuple("Other" if i in (5, 9) else v for i, v in enumerate(rows[4]))
    with pytest.raises(QpcLayoutError, match="appears 0 times"):
        _run(rows)


def test_header_missing() -> None:
    with pytest.raises(QpcLayoutError, match="header 'NAICS Code"):
        _run([HEADER_ROWS[0], (), (3112, "Ok", "c", 1.0)])


def test_no_data_rows() -> None:
    with pytest.raises(QpcDataError, match="no data rows"):
        _run(sheet_rows())


def test_too_few_codes() -> None:
    with pytest.raises(QpcDataError, match="only 1 four-digit codes"):
        _run(
            sheet_rows(data_row(3112, "Ok", 10.0)),
            settings=dataclasses.replace(_settings(), min_codes=5),
        )


def test_code_without_description_is_a_layout_problem() -> None:
    with pytest.raises(QpcDataError, match="no description"):
        _run(sheet_rows(data_row(3112, None, 10.0)))


def test_edition_matches() -> None:
    check_edition([(INTRO,)], _settings())


def test_edition_mismatch() -> None:
    with pytest.raises(QpcLayoutError, match="NAICS 2017, expected 2022"):
        check_edition(
            [("Based on the 2017 edition of the North American Industry Classification",)],
            _settings(),
        )


def test_edition_not_stated() -> None:
    with pytest.raises(QpcLayoutError, match="does not state a NAICS edition"):
        check_edition([("nothing here",)], _settings())
