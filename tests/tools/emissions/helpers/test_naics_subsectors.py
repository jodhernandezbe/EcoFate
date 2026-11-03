"""Tests for the local NAICS subsector table (synthetic codes and titles)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from config.industry import IndustrySettings, load_industry_settings
from tests.tools.emissions.records import emission_record
from tools.emissions.helpers.naics_subsectors import (
    subsector_of,
    subsector_titles,
    with_subsectors,
)
from tools.schemas import EmissionRecord

SETTINGS = load_industry_settings()
TABLE = "naics_subsector,title,vintage\n111,Synthetic Crops,2022\n222, Spaced   Title ,2017\n"


def _table(tmp_path: Path, text: str = TABLE, name: str = "sub.csv") -> IndustrySettings:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return replace(SETTINGS, subsectors_path=path)


def _record(code: str | None) -> EmissionRecord:
    return {**emission_record("F1", 1.0), "naics_code": code}


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("325211", "325"), ("3252", "325"), ("325", "325"), ("32", None), ("", None), (None, None),
        ("a25211", None), ("32 5211", None),
    ],
)  # fmt: skip
def test_subsector_of(code: str | None, expected: str | None) -> None:
    assert subsector_of(code) == expected


def test_reads_codes_and_titles(tmp_path: Path) -> None:
    titles = subsector_titles(_table(tmp_path))
    assert titles["111"] == "Synthetic Crops"
    assert titles["222"] == "Spaced Title"
    assert "333" not in titles


def test_the_table_is_read_only(tmp_path: Path) -> None:
    titles = subsector_titles(_table(tmp_path))
    with pytest.raises(TypeError):
        titles["444"] = "x"  # type: ignore[index]


def test_a_six_digit_code_gets_its_subsector_and_title(tmp_path: Path) -> None:
    out = with_subsectors([_record("111110")], subsector_titles(_table(tmp_path)))
    assert (out[0]["naics_subsector"], out[0]["naics_subsector_title"]) == (
        "111",
        "Synthetic Crops",
    )


def test_a_short_or_missing_code_has_neither(tmp_path: Path) -> None:
    titles = subsector_titles(_table(tmp_path))
    for code in (None, "31"):
        out = with_subsectors([_record(code)], titles)[0]
        assert (out["naics_subsector"], out["naics_subsector_title"]) == (None, None)


def test_an_unlisted_subsector_keeps_the_code_with_a_null_title(tmp_path: Path) -> None:
    out = with_subsectors([_record("999999")], subsector_titles(_table(tmp_path)))[0]
    assert (out["naics_subsector"], out["naics_subsector_title"]) == ("999", None)


def test_other_fields_and_the_input_are_untouched(tmp_path: Path) -> None:
    original = _record("111110")
    out = with_subsectors([original], subsector_titles(_table(tmp_path)))[0]
    assert original["naics_subsector"] is None  # a copy was made
    assert {k: v for k, v in out.items() if not k.startswith("naics_subsector")} == {
        k: v for k, v in original.items() if not k.startswith("naics_subsector")
    }


def test_the_table_is_read_once(tmp_path: Path) -> None:
    settings = _table(tmp_path)
    assert subsector_titles(settings) is subsector_titles(settings)


def test_a_missing_file_or_column_is_a_setup_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        subsector_titles(replace(SETTINGS, subsectors_path=tmp_path / "none.csv"))
    with pytest.raises(ValueError, match="naics_subsector"):
        subsector_titles(_table(tmp_path, "x,title\n111,A\n", name="bad.csv"))


def test_the_committed_table_resolves_a_chemical_code() -> None:
    out = with_subsectors([_record("325211")], subsector_titles(SETTINGS))[0]
    assert out["naics_subsector_title"] == "Chemical Manufacturing"
