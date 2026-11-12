"""Tests for the ECETOC TRA tier-1 band estimate."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.ecetoc_tra import EcetocTraSettings, get_ecetoc_tra_settings
from tools.assessment.helpers.occupational_bands import ecetoc

HEADER = "kind,proc,band,min_hours,max_hours,value,unit\n"
DURATIONS = "duration,,,2,24,1.0,\nduration,,,0,2,0.5,\n"
ESTIMATES = "estimate,9z,high,,,200,ppm\nestimate,9z,low,,,4,ppm\n"
SETTINGS = EcetocTraSettings(Path("unused.csv"), 0.5, 100.0, 1000.0)
MOLAR_VOLUME = 25.0


def _table(tmp_path: Path, body: str = ESTIMATES + DURATIONS) -> ecetoc.TraTable:
    path = tmp_path / "table.csv"
    path.write_text("# a comment, with a comma\n" + HEADER + body)
    return ecetoc.parse_table(path)


def _estimate(
    table: ecetoc.TraTable,
    proc: str | None = "9z",
    vapor_pressure_pa: float = 5000.0,
    molecular_weight: float | None = 50.0,
    hours: float = 1.0,
) -> ecetoc.BandEstimate:
    return ecetoc.estimate(
        proc,
        vapor_pressure_pa,
        molecular_weight,
        hours,
        MOLAR_VOLUME,
        table,
        SETTINGS,
    )


def test_high_volatility_converts_and_applies_duration(tmp_path: Path) -> None:
    result = _estimate(_table(tmp_path), vapor_pressure_pa=5000.0)
    assert result.band == "high" and result.ppm == 200.0 and result.proc == "9z"
    assert result.worst_case_mg_m3 == pytest.approx(200.0 * 50.0 / MOLAR_VOLUME)
    assert result.worst_case_mg_m3 is not None
    assert result.baseline_mg_m3 == pytest.approx(result.worst_case_mg_m3 * 0.5)
    assert result.statement is not None and "tier-1" in result.statement
    assert "local exhaust" in result.statement and result.reason is None


def test_unmapped_activity_has_no_estimate(tmp_path: Path) -> None:
    result = _estimate(_table(tmp_path), proc=None)
    assert result.ppm is None and result.statement is None
    assert result.reason is not None and "process category" in result.reason


@pytest.mark.parametrize("weight", [None, 0.0, -1.0, float("nan"), True])
def test_missing_or_invalid_molecular_weight(tmp_path: Path, weight: float | None) -> None:
    result = _estimate(_table(tmp_path), molecular_weight=weight)
    assert result.baseline_mg_m3 is None
    assert result.reason is not None and "molecular weight" in result.reason


def test_band_without_a_value_has_no_estimate(tmp_path: Path) -> None:
    result = _estimate(_table(tmp_path), vapor_pressure_pa=300.0)  # moderate
    assert result.band == "moderate" and result.ppm is None
    assert result.reason is not None and "moderate" in result.reason


def test_unknown_proc_has_no_estimate(tmp_path: Path) -> None:
    assert _estimate(_table(tmp_path), proc="1x").reason is not None


@pytest.mark.parametrize(
    ("pressure", "band"),
    [
        (0.0, "very_low"),
        (0.49, "very_low"),
        (0.5, "low"),
        (100.0, "low"),
        (100.1, "moderate"),
        (1000.0, "moderate"),
        (1000.1, "high"),
    ],
)
def test_band_boundaries(pressure: float, band: str) -> None:
    assert ecetoc.volatility_band(pressure, SETTINGS) == band


@pytest.mark.parametrize("pressure", [-1.0, float("nan"), float("inf"), True])
def test_band_rejects_invalid_pressure(pressure: float) -> None:
    with pytest.raises(ValueError):
        ecetoc.volatility_band(pressure, SETTINGS)


@pytest.mark.parametrize(
    ("hours", "factor"),
    [(0.0, 0.5), (1.99, 0.5), (2.0, 1.0), (10.0, 1.0)],
)
def test_duration_boundaries(tmp_path: Path, hours: float, factor: float) -> None:
    table = _table(tmp_path)
    assert ecetoc.duration_factor(hours, table) == factor
    assert ecetoc.duration_factor(24.0, table) == 1.0


@pytest.mark.parametrize("hours", [-0.1, 24.1, float("nan"), True])
def test_duration_rejects_invalid_hours(tmp_path: Path, hours: float) -> None:
    table = _table(tmp_path)
    with pytest.raises(ValueError):
        ecetoc.duration_factor(hours, table)


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        ("other,9z,high,,,1,ppm\n", "kind"),
        ("estimate,9z,huge,,,1,ppm\n", "band"),
        ("estimate,9z,high,,,1,mg\n", "ppm"),
        ("estimate,,high,,,1,ppm\n", "proc"),
        ("estimate,9z,high,,,-1,ppm\n", "non-negative"),
        ("estimate,9z,high,,,nan,ppm\n", "finite"),
        ("estimate,9z,high,,,abc,ppm\n", "number"),
        ("estimate,9z,high\n", "fields"),
        ("duration,,,5,2,1.0,\n", "below max_hours"),
    ],
)
def test_malformed_row_names_the_line(tmp_path: Path, row: str, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment) as raised:
        _table(tmp_path, DURATIONS + row)
    assert "table.csv line 5" in str(raised.value)


@pytest.mark.parametrize(
    "durations",
    [
        "duration,,,0,2,0.5,\nduration,,,3,24,1.0,\n",
        "duration,,,0,2,0.5,\nduration,,,2,10,1.0,\n",
        "",
    ],
)
def test_duration_rows_must_cover_zero_to_24(tmp_path: Path, durations: str) -> None:
    with pytest.raises(ValueError, match="duration rows"):
        _table(tmp_path, ESTIMATES + durations)


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing.csv"):
        ecetoc.parse_table(tmp_path / "missing.csv")


def test_wrong_header_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="header"):
        ecetoc.parse_table(path)


def test_table_is_cached_and_immutable(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    path.write_text(HEADER + ESTIMATES + DURATIONS)
    table = ecetoc.load_table(path)
    assert ecetoc.load_table(path) is table
    with pytest.raises(TypeError):
        table.estimates[("9z", "low")] = 1.0  # type: ignore[index]


def test_bundled_table_parses() -> None:
    settings = get_ecetoc_tra_settings()
    table = ecetoc.parse_table(settings.table_path)
    assert table.estimates[("8a", "high")] == 250.0
    assert ecetoc.duration_factor(24.0, table) == table.durations[-1].factor
