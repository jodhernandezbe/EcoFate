"""Tests for the CDR industrial sector of a NAICS code."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from config.cdr_sector import CdrSectorSettings, get_cdr_sector_settings
from tools.emissions.helpers.inventory.sector import (
    load_sector_table,
    sector_for,
)

SHIPPED = get_cdr_sector_settings()


def _settings(path: Path) -> CdrSectorSettings:
    return CdrSectorSettings(path, "naics_prefix", "is_code", "is_title", "naics_edition", 2, 6)


def _file(tmp_path: Path, rows: list[list[str]]) -> CdrSectorSettings:
    path = tmp_path / "x.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["naics_prefix", "is_code", "is_title", "naics_edition"])
        writer.writerows(rows)
    return _settings(path)


def test_longest_prefix_wins(tmp_path: Path) -> None:
    settings = _file(
        tmp_path,
        [["325", "IS1", "General", "2007"], ["3251", "IS2", "Basic", "2007"]],
    )
    table = load_sector_table(settings)
    found, why = sector_for("325199", table, settings)
    assert why is None and found is not None
    assert (found["code"], found["matched_naics_prefix"], found["naics_edition"]) == (
        "IS2",
        "3251",
        "2007",
    )


def test_a_longer_baseline_code_is_never_matched(tmp_path: Path) -> None:
    settings = _file(tmp_path, [["325199", "IS9", "Specific", "2007"]])
    found, why = sector_for("3251", load_sector_table(settings), settings)
    assert found is None and why is not None


@pytest.mark.parametrize("code", [None, "", "x1", "3", "1234567", " "])
def test_unusable_codes_give_no_sector(tmp_path: Path, code: str | None) -> None:
    settings = _file(tmp_path, [["325", "IS1", "General", "2007"]])
    found, why = sector_for(code, load_sector_table(settings), settings)
    assert found is None and why == "no usable NAICS code"


def test_no_prefix_in_the_file_is_not_inferred(tmp_path: Path) -> None:
    settings = _file(tmp_path, [["325", "IS1", "General", "2007"]])
    found, why = sector_for("999999", load_sector_table(settings), settings)
    assert found is None and "has no industrial sector" in (why or "")


def test_bad_and_repeated_rows_are_ignored_and_counted(tmp_path: Path) -> None:
    settings = _file(
        tmp_path,
        [
            ["325", "IS1", "General", "2007"],
            ["3x5", "IS2", "Bad prefix", "2007"],
            ["331", "XX3", "Bad code", "2007"],
            ["332", "IS4", "", "2007"],
            ["333", "IS5", "Twice", "2007"],
            ["333", "IS6", "Twice", "2007"],
        ],
    )
    table = load_sector_table(settings)
    assert set(table.rows) == {"325"}
    assert any("ignored 5" in w for w in table.warnings)


def test_missing_or_malformed_file_gives_an_empty_table(tmp_path: Path) -> None:
    missing = load_sector_table(_settings(tmp_path / "none.csv"))
    assert not missing.rows and missing.warnings
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    assert not load_sector_table(_settings(bad)).rows
    found, why = sector_for("325199", missing, _settings(tmp_path / "none.csv"))
    assert found is None and why == "CDR sector crosswalk unavailable"


def test_shipped_crosswalk_matches_epas_table() -> None:
    table = load_sector_table(SHIPPED)
    assert not table.warnings
    expected = {
        "325199": "IS21",  # other basic organic chemical manufacturing
        "325211": "IS22",  # plastic material and resin manufacturing
        "324110": "IS11",  # petroleum refineries
        "331110": "IS38",  # primary metal manufacturing
        "562211": "IS47",  # services
        "424690": "IS46",  # wholesale trade
    }
    for naics, sector in expected.items():
        found, _ = sector_for(naics, table, SHIPPED)
        assert found is not None and found["code"] == sector, naics


def test_shipped_crosswalk_has_unique_sectors_in_range() -> None:
    table = load_sector_table(SHIPPED)
    codes = {code for code, _, _ in table.rows.values()}
    assert codes <= {f"IS{n}" for n in range(1, 49)}
    assert {"IS1", "IS47"} <= codes and len(table.rows) >= 60
