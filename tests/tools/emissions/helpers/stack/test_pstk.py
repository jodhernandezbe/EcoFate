"""Tests for the tier 2 PSTK lookup and the global fallback.

Fixture files use obviously fake SCCs (999...) and round numbers, not real PSTK data.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from config.stack import StackSettings, load_stack_settings
from tools.emissions.helpers.stack.pstk import normalize_scc, read_pstk, scc_stack_parameters
from tools.schemas import StackParameters

HEADER = "fips,scc,stkhgt,stkdiam,stkvel,stktemp\n"
ROWS = (
    "0,99900001,10,1,5,400\n"  # national
    "00000,99900002,20,2,6,450\n"  # national, other marker
    ",99900003,30,3,7,500\n"  # empty FIPS: national
    "01001,99900004,40,4,8,550\n"  # county-specific only: ignored
    "0,99900005,10,1,5,100\n"  # implausible temperature
    "0,99900006,10,1,5,400\n"
    "0,99900006,11,1,5,400\n"  # duplicate national row
    "0,0,3,0.2,4,295.4\n"  # the file's own global default row: not an SCC
)
FALLBACK = {
    "stack_height": 3.0,
    "stack_diameter": 0.2,
    "exit_velocity": 4.0,
    "exit_temperature": 295.4,
}


def _settings(tmp_path: Path, text: str = HEADER + ROWS, **pstk: object) -> StackSettings:
    path = tmp_path / "pstk.csv"
    path.write_text(text)
    settings = load_stack_settings()
    return replace(settings, pstk=replace(settings.pstk, path=path, **pstk))  # type: ignore[arg-type]


def _values(result: StackParameters) -> dict[str, float | None]:
    return {
        "stack_height": result["stack_height"],
        "stack_diameter": result["stack_diameter"],
        "exit_velocity": result["exit_velocity"],
        "exit_temperature": result["exit_temperature"],
    }


def test_scc_found(tmp_path: Path) -> None:
    result = scc_stack_parameters("99900001", _settings(tmp_path), None)
    assert _values(result) == {
        "stack_height": 10.0,
        "stack_diameter": 1.0,
        "exit_velocity": 5.0,
        "exit_temperature": 400.0,
    }
    assert result["source"] == "PSTK"
    assert result["scc"] == "99900001"
    assert result["warnings"] == []


@pytest.mark.parametrize("code", [" 99900003 ", "99900003", 99900003])
def test_scc_whitespace_and_integer_accepted(tmp_path: Path, code: str) -> None:
    result = scc_stack_parameters(code, _settings(tmp_path), None)
    assert result["source"] == "PSTK"
    assert result["stack_height"] == 30.0


@pytest.mark.parametrize("code", ["099900003", "0099900003", "9990000"])
def test_scc_must_match_exactly(tmp_path: Path, code: str) -> None:
    """A code with an extra leading zero (or a missing digit) is another code, not a match."""
    result = scc_stack_parameters(code, _settings(tmp_path), None)
    assert result["source"] == "AirToxScreen global default"
    assert f"SCC {code} was not found in PSTK" in result["warnings"][0]


@pytest.mark.parametrize("code", ["0", "00", 0])
def test_global_default_row_is_not_an_scc(tmp_path: Path, code: str | int) -> None:
    settings = _settings(tmp_path)
    table, _ = read_pstk(settings.pstk)
    assert table is not None
    assert "0" not in table.rows
    result = scc_stack_parameters(code, settings, None)
    assert result["source"] == "AirToxScreen global default"
    assert "was not found in PSTK" in result["warnings"][0]


def test_matched_scc_is_the_canonical_code(tmp_path: Path) -> None:
    for code in (" 99900001 ", 99900001):
        assert scc_stack_parameters(code, _settings(tmp_path), None)["scc"] == "99900001"


@pytest.mark.parametrize("code", [True, False, -99900001])
def test_boolean_and_negative_numbers_are_invalid(tmp_path: Path, code: int) -> None:
    settings = _settings(tmp_path)
    settings.pstk.path.unlink()  # never read
    result = scc_stack_parameters(code, settings, None)
    assert result["source"] == "AirToxScreen global default"
    assert "is invalid" in result["warnings"][0]


def test_other_national_marker(tmp_path: Path) -> None:
    assert scc_stack_parameters("99900002", _settings(tmp_path), None)["stack_height"] == 20.0


def test_county_rows_ignored(tmp_path: Path) -> None:
    result = scc_stack_parameters("99900004", _settings(tmp_path), None)
    assert result["source"] == "AirToxScreen global default"
    assert "not found in PSTK" in result["warnings"][0]


def test_no_fips_column_means_all_national(tmp_path: Path) -> None:
    settings = _settings(tmp_path, fips_column=None)
    assert scc_stack_parameters("99900004", settings, None)["stack_height"] == 40.0


def test_duplicate_rows_first_used(tmp_path: Path) -> None:
    result = scc_stack_parameters("99900006", _settings(tmp_path), None)
    assert result["stack_height"] == 10.0
    assert result["warnings"] == [
        "PSTK lists 2 national rows for SCC 99900006; the first one was used",
    ]


def test_unit_conversion_from_file_units(tmp_path: Path) -> None:
    units = MappingProxyType(
        {
            "stack_height": "ft",
            "stack_diameter": "ft",
            "exit_velocity": "ft/s",
            "exit_temperature": "degF",
        },
    )
    result = scc_stack_parameters("99900001", _settings(tmp_path, units=units), None)
    assert result["stack_height"] == pytest.approx(3.048)
    assert result["exit_temperature"] == pytest.approx(477.594, abs=1e-3)


def test_scc_not_found_global_default(tmp_path: Path) -> None:
    result = scc_stack_parameters("99999999", _settings(tmp_path), None)
    assert _values(result) == FALLBACK
    assert result["source"] == "AirToxScreen global default"
    assert result["scc"] is None
    assert "SCC 99999999 was not found in PSTK" in result["warnings"][0]
    assert "AirToxScreen global default" in result["warnings"][0]


@pytest.mark.parametrize("code", ["", "   ", "3060-0101", "abc", "1.5", "²", "\u0663\u0660"])
def test_malformed_scc_global_default(tmp_path: Path, code: str) -> None:
    settings = _settings(tmp_path)
    settings.pstk.path.unlink()  # never read: an invalid SCC must not search the file
    result = scc_stack_parameters(code, settings, None)
    assert _values(result) == FALLBACK
    assert "is invalid" in result["warnings"][0]


def test_no_scc_global_default_without_reading_pstk(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.pstk.path.unlink()  # never read: with no SCC there is nothing to search
    result = scc_stack_parameters(None, settings, None)
    assert _values(result) == FALLBACK
    assert result["source"] == "AirToxScreen global default"
    assert result["scc"] is None
    assert result["warnings"] == [
        "no SCC was given; using the AirToxScreen global default (generic, not facility-specific)",
    ]


def test_implausible_row_not_mixed(tmp_path: Path) -> None:
    result = scc_stack_parameters("99900005", _settings(tmp_path), None)
    assert _values(result) == FALLBACK
    assert result["source"] == "AirToxScreen global default"
    assert "exit_temperature 100 K is outside the plausible range" in result["warnings"][0]


def test_missing_file_global_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.pstk.path.unlink()
    result = scc_stack_parameters("99900001", settings, None)
    assert _values(result) == FALLBACK
    assert "could not be read" in result["warnings"][0]


def test_missing_configured_column_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path, HEADER.replace("stktemp", "temp") + ROWS)
    with pytest.raises(ValueError, match="lacks configured columns: stktemp"):
        scc_stack_parameters("99900001", settings, None)


def test_unconvertible_unit_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    units = MappingProxyType({**settings.pstk.units, "stack_height": "kg"})
    with pytest.raises(ValueError, match="stack_height"):
        scc_stack_parameters(
            "99900001",
            replace(settings, pstk=replace(settings.pstk, units=units)),
            None,
        )


def test_changed_file_reread(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert scc_stack_parameters("99900001", settings, None)["stack_height"] == 10.0
    settings.pstk.path.write_text(HEADER + "0,99900001,12,1,5,400\n")
    stat = settings.pstk.path.stat()
    os.utime(settings.pstk.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert scc_stack_parameters("99900001", settings, None)["stack_height"] == 12.0


def test_read_returns_copies(tmp_path: Path) -> None:
    table, _ = read_pstk(_settings(tmp_path).pstk)
    assert table is not None
    with pytest.raises(TypeError):
        table.rows["1"] = {}  # type: ignore[index]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("30600101", "30600101"),
        (" 30600101 ", "30600101"),
        (30600101, "30600101"),
        ("030600101", "030600101"),  # not stripped: fixed-length codes
        ("000", "000"),
        ("3a", None),
        ("", None),
        (True, None),
        (-5, None),
    ],
)
def test_normalize_scc(code: str | int, expected: str | None) -> None:
    assert normalize_scc(code) == expected
