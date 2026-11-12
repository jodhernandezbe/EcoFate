"""Tests for the OSHA monitoring lookup (synthetic tables, never the bundled files)."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.osha_cehd import OshaCehdSettings, load_osha_cehd_settings
from tools.assessment.helpers.monitoring.cehd import (
    MonitoringTable,
    get_table,
    load_table,
    lookup,
)

SETTINGS_TEXT = """
[osha_cehd]
url_pattern = "https://example.test/{year}.zip"
crosswalk_url_pattern = "https://example.test/list?page={page}"
user_agent = "agent"
timeout_s = 30
years = [2020, 2021]
naics_prefix_lengths = [6, 4, 3]
min_values = 5
molar_volume_l_per_mol = 24.45
summary_path = "SUMMARY"
crosswalk_path = "CROSSWALK"
nondetect_qualifiers = ["ND"]
blank_marker = "BLK"
[osha_cehd.units]
M = "mg/m^3"
P = "ppm"
"""
HEADER = "imis,naics_prefix,unit,n,n_nd,median,p95,first_year,last_year\n"
COMMENT = "# OSHA CEHD personal air samples, years 2020-2021, built 2026-01-02\n"
CROSSWALK = (
    "imis_code,cas,substance,source\nAAAA,000-00-0,SYNTHETIC ONE,x\nBBBB,000-00-0,SYNTHETIC TWO,x\n"
)
CAS = "000-00-0"


def _settings(tmp_path: Path) -> OshaCehdSettings:
    text = SETTINGS_TEXT.replace("SUMMARY", str(tmp_path / "s.csv"))
    text = text.replace("CROSSWALK", str(tmp_path / "c.csv"))
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_osha_cehd_settings(path)


def _table(tmp_path: Path, rows: list[str], crosswalk: str = CROSSWALK) -> MonitoringTable:
    settings = _settings(tmp_path)
    settings.summary_path.write_text(COMMENT + HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    settings.crosswalk_path.write_text(crosswalk, encoding="utf-8")
    return load_table(settings.summary_path, settings.crosswalk_path)


def test_specific_industry_has_enough(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,6,1,2.0,9.0,2020,2021", "AAAA,3251,mg/m^3,40,5,1.0,5.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert result.available
    assert (result.level_digits, result.naics_level, result.level_note) == (6, "325110", None)
    assert (result.n_values, result.n_nondetect) == (6, 1)
    assert (result.median_mg_m3, result.p95_mg_m3) == (2.0, 9.0)
    assert (result.first_year, result.last_year) == (2020, 2021)


def test_falls_back_to_broader_industry(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,4,0,2.0,9.0,2020,2021", "AAAA,3251,mg/m^3,40,5,1.0,5.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert (result.level_digits, result.naics_level) == (4, "3251")
    assert result.level_note is not None
    assert "4-digit prefix 3251" in result.level_note


def test_too_few_everywhere_gives_number_found(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,2,0,2.0,9.0,2020,2021", "AAAA,325,mg/m^3,4,0,1.0,5.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert not result.available
    assert result.n_found == 4
    assert result.reason is not None
    assert "4 values found" in result.reason
    assert result.median_mg_m3 is None


def test_shorter_naics_skips_longer_levels(tmp_path: Path) -> None:
    rows = ["AAAA,3251,mg/m^3,9,0,2.0,9.0,2020,2021"]
    result = lookup(CAS, "3251", None, _settings(tmp_path), _table(tmp_path, rows))
    assert result.available
    assert result.level_digits == 4
    assert result.level_note is not None


def test_ppm_row_is_converted(tmp_path: Path) -> None:
    rows = ["AAAA,325110,ppm,8,0,10.0,20.0,2020,2021"]
    result = lookup(CAS, "325110", 100.0, _settings(tmp_path), _table(tmp_path, rows))
    assert result.original_unit == "ppm"
    assert result.median_mg_m3 == pytest.approx(10.0 * 100.0 / 24.45)
    assert result.p95_mg_m3 == pytest.approx(20.0 * 100.0 / 24.45)


@pytest.mark.parametrize("weight", [None, 0.0, -5.0, float("nan"), float("inf")])
def test_ppm_row_without_usable_molecular_weight(tmp_path: Path, weight: float | None) -> None:
    rows = ["AAAA,325110,ppm,8,0,10.0,20.0,2020,2021"]
    result = lookup(CAS, "325110", weight, _settings(tmp_path), _table(tmp_path, rows))
    assert not result.available
    assert result.reason is not None
    assert "molecular weight" in result.reason


def test_mg_row_does_not_need_molecular_weight(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,8,0,10.0,20.0,2020,2021"]
    assert lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows)).available


def test_median_below_detection(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,10,6,0.0,3.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert result.available
    assert result.median_mg_m3 is None
    assert result.reason == "below detection"
    assert result.p95_mg_m3 == 3.0


def test_half_nondetects_is_not_below_detection(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,10,5,0.2,3.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert result.median_mg_m3 == 0.2
    assert result.reason is None


def test_unit_with_more_values_is_used_and_said(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021", "AAAA,325110,ppm,20,0,1.0,2.0,2020,2021"]
    result = lookup(CAS, "325110", 50.0, _settings(tmp_path), _table(tmp_path, rows))
    assert result.original_unit == "ppm"
    assert result.n_values == 20
    assert result.unit_note is not None
    assert "most values" in result.unit_note


def test_unit_with_too_few_values_is_not_chosen(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021", "AAAA,325110,ppm,3,0,1.0,2.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert result.original_unit == "mg/m^3"
    assert result.unit_note is None


def test_cas_with_two_imis_codes_uses_the_larger_group(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021", "BBBB,325110,mg/m^3,9,0,3.0,9.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    assert result.imis_code == "BBBB"


def test_unknown_cas_has_no_data(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021"]
    result = lookup("999-99-9", "325110", 100.0, _settings(tmp_path), _table(tmp_path, rows))
    assert not result.available
    assert result.reason is not None
    assert "no substance with CAS number 999-99-9" in result.reason


@pytest.mark.parametrize("naics", ["", "abc", "  "])
def test_missing_naics(tmp_path: Path, naics: str) -> None:
    rows = ["AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021"]
    result = lookup(CAS, naics, None, _settings(tmp_path), _table(tmp_path, rows))
    assert not result.available
    assert result.reason is not None
    assert "NAICS" in result.reason


def test_limits_of_the_data_are_stated(tmp_path: Path) -> None:
    rows = ["AAAA,325110,mg/m^3,6,1,2.0,9.0,2020,2021"]
    result = lookup(CAS, "325110", None, _settings(tmp_path), _table(tmp_path, rows))
    text = " ".join(result.statements)
    assert "not from the facility assessed" in text
    assert "not a representative sample" in text
    assert "2020 to 2021" in text
    assert "6 values, 1 non-detects" in text
    assert "years 2020-2021" in text
    assert "OSHA" in result.source


def test_limits_are_stated_when_no_data(tmp_path: Path) -> None:
    result = lookup("999-99-9", "325110", None, _settings(tmp_path), _table(tmp_path, []))
    assert any("not a representative sample" in s for s in result.statements)


@pytest.mark.parametrize(
    "row",
    [
        "AAAA,325110,mg/m^3,x,0,2.0,9.0,2020,2021",
        "AAAA,325110,percent,6,0,2.0,9.0,2020,2021",
        "AAAA,325110,mg/m^3,6,7,2.0,9.0,2020,2021",
        "AAAA,325110,mg/m^3,6,0,nan,9.0,2020,2021",
        "AAAA,325110,mg/m^3,0,0,2.0,9.0,2020,2021",
    ],
)
def test_malformed_summary_raises(tmp_path: Path, row: str) -> None:
    with pytest.raises(ValueError, match="OSHA summary row"):
        _table(tmp_path, [row])


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_table(tmp_path / "none.csv", tmp_path / "none2.csv")


def test_comment_line_is_skipped_and_table_is_immutable(tmp_path: Path) -> None:
    table = _table(tmp_path, ["AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021"])
    assert len(table.rows) == 1
    assert "years 2020-2021" in table.window
    with pytest.raises(TypeError):
        table.rows[("x", "y", "z")] = None  # type: ignore[index]


def test_table_is_read_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.summary_path.write_text(
        HEADER + "AAAA,325110,mg/m^3,6,0,2.0,9.0,2020,2021\n",
        encoding="utf-8",
    )
    settings.crosswalk_path.write_text(CROSSWALK, encoding="utf-8")
    assert get_table(settings) is get_table(settings)
