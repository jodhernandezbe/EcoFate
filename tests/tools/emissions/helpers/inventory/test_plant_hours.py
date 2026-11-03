"""Tests for the plant-hours baseline and resolver (synthetic parquet files, placeholder hours)."""

# pyarrow ships no type information, so strict mode cannot see through its objects here.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from config.plant_hours import PlantHoursSettings, get_plant_hours_settings
from tools.emissions.helpers.inventory.plant_hours import (
    PlantHours,
    _valid_hours,  # pyright: ignore[reportPrivateUsage]
    get_baseline,
    load_baseline,
)

DEFAULT = 8760.0


def _write(
    path: Path,
    codes: list[object],
    hours: list[object],
    release: str | None = "2026Q2",
) -> Path:
    table = pa.table({"naics_code": pa.array(codes), "avg_plant_hours_per_week": pa.array(hours)})
    if release:
        table = table.replace_schema_metadata({"qpc.release": release})
    pq.write_table(table, path)
    return path


def _settings(path: Path, **changes: object) -> PlantHoursSettings:
    return dataclasses.replace(get_plant_hours_settings(), baseline_path=path, **changes)  # type: ignore[arg-type]


def _resolver(tmp_path: Path, codes: list[object], hours: list[object]) -> PlantHours:
    settings = _settings(_write(tmp_path / "b.parquet", codes, hours))
    return PlantHours(load_baseline(settings), settings, DEFAULT)


def test_exact_six_digit_match_beats_shorter(tmp_path: Path) -> None:
    resolve = _resolver(tmp_path, ["325211", "3252"], [84.0, 100.0])
    got = resolve("325211")
    assert got.hours_per_year == pytest.approx(84 * 365 / 7) == pytest.approx(4380)
    assert got.source == "Census QPC 2026Q2, NAICS 325211: 84 plant hours/week"


def test_falls_back_to_a_shorter_code(tmp_path: Path) -> None:
    resolve = _resolver(tmp_path, ["3252", "325"], [50.0, 60.0])
    assert resolve("325211").source.endswith("NAICS 3252: 50 plant hours/week")


def test_specific_beats_general_across_lengths(tmp_path: Path) -> None:
    resolve = _resolver(tmp_path, ["325", "3252", "32521"], [10.0, 20.0, 30.0])
    assert resolve("325211").source.endswith("NAICS 32521: 30 plant hours/week")


def test_never_matches_a_more_specific_baseline_code(tmp_path: Path) -> None:
    resolve = _resolver(tmp_path, ["325211"], [84.0])
    got = resolve("3252")
    assert got.hours_per_year == DEFAULT and "no QPC match for 3252" in got.source


def test_continuous_operation_is_exactly_a_year(tmp_path: Path) -> None:
    assert _resolver(tmp_path, ["3252"], [168.0])("325211").hours_per_year == 8760.0


def test_integer_hours_are_accepted(tmp_path: Path) -> None:
    assert _resolver(tmp_path, ["3252"], [84])("325211").hours_per_year == pytest.approx(4380)


def test_no_match_uses_the_default_and_says_why(tmp_path: Path) -> None:
    got = _resolver(tmp_path, ["3252"], [84.0])("324110")
    assert got.hours_per_year == DEFAULT
    assert got.source == "default 8760 h/yr (no QPC match for 324110)"


@pytest.mark.parametrize("code", [None, "", "  ", "3a2", "5", "1234567", "-3252", "32 52"])
def test_unusable_codes_use_the_default(tmp_path: Path, code: str | None) -> None:
    got = _resolver(tmp_path, ["3252"], [84.0])(code)
    assert got.hours_per_year == DEFAULT and got.source.startswith("default 8760 h/yr (no usable")


def test_two_digit_code_is_below_the_minimum(tmp_path: Path) -> None:
    got = _resolver(tmp_path, ["325"], [84.0])("32")
    assert got.hours_per_year == DEFAULT and "no QPC match for 32" in got.source


@pytest.mark.parametrize("bad", [0, -1, 169, float("nan"), float("inf"), None])
def test_bad_hours_rows_are_ignored_others_still_match(tmp_path: Path, bad: object) -> None:
    settings = _settings(_write(tmp_path / "b.parquet", ["3251", "3252"], [bad, 84.0]))
    baseline = load_baseline(settings)
    assert dict(baseline.hours_per_week) == {"3252": 84.0}
    assert "ignored 1 unusable rows" in baseline.warnings[0]


@pytest.mark.parametrize("code", ["32", "3252xx", "1234567", "abcd", " 3252", None])
def test_bad_code_rows_are_ignored(tmp_path: Path, code: object) -> None:
    settings = _settings(_write(tmp_path / "b.parquet", [code, "3253"], [50.0, 60.0]))
    assert dict(load_baseline(settings).hours_per_week) == {"3253": 60.0}


def test_duplicate_code_uses_neither_row(tmp_path: Path) -> None:
    settings = _settings(_write(tmp_path / "b.parquet", ["3252", "3252", "3253"], [1.0, 2.0, 3.0]))
    baseline = load_baseline(settings)
    assert dict(baseline.hours_per_week) == {"3253": 3.0}
    assert "ignored 2 unusable rows" in baseline.warnings[0]


def test_missing_file_gives_the_default_with_one_warning(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "none.parquet")
    baseline = load_baseline(settings)
    assert not baseline.hours_per_week and len(baseline.warnings) == 1
    assert "none.parquet" in baseline.warnings[0]
    got = PlantHours(baseline, settings, DEFAULT)("325211")
    assert got.hours_per_year == DEFAULT and "QPC baseline unavailable" in got.source


def test_missing_column_rejects_the_file(tmp_path: Path) -> None:
    settings = _settings(_write(tmp_path / "b.parquet", ["3252"], [84.0]), hours_column="nope")
    baseline = load_baseline(settings)
    assert not baseline.hours_per_week and "missing column nope" in baseline.warnings[0]


def test_missing_release_metadata_rejects_the_file(tmp_path: Path) -> None:
    settings = _settings(_write(tmp_path / "b.parquet", ["3252"], [84.0], release=None))
    baseline = load_baseline(settings)
    assert not baseline.hours_per_week and "no release" in baseline.warnings[0]


def test_not_a_parquet_file_is_unavailable_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "b.parquet"
    path.write_bytes(b"not parquet")
    assert not load_baseline(_settings(path)).hours_per_week


def test_renamed_columns_are_read_from_configuration(tmp_path: Path) -> None:
    path = tmp_path / "b.parquet"
    table = pa.table({"code": ["3252"], "hrs": [84.0]}).replace_schema_metadata(
        {"qpc.release": "2026Q2"},
    )
    pq.write_table(table, path)
    settings = _settings(path, code_column="code", hours_column="hrs")
    assert dict(load_baseline(settings).hours_per_week) == {"3252": 84.0}


def test_baseline_is_read_once_for_many_lookups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    get_baseline.cache_clear()
    settings = _settings(_write(tmp_path / "b.parquet", ["3252", "3253"], [1.0, 2.0]))
    reads: list[Path] = []
    real = pq.read_table
    monkeypatch.setattr(
        "tools.emissions.helpers.inventory.plant_hours.pq.read_table",
        lambda path, **kw: (reads.append(Path(str(path))), real(path, **kw))[1],
    )
    with caplog.at_level(logging.WARNING):
        resolve = PlantHours(get_baseline(settings), settings, DEFAULT)
        for _ in range(50):
            resolve("325211")
            get_baseline(settings)
    assert len(reads) == 1
    get_baseline.cache_clear()


def test_baseline_problem_is_logged_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    get_baseline.cache_clear()
    settings = _settings(tmp_path / "none.parquet")
    with caplog.at_level(logging.WARNING):
        get_baseline(settings)
        get_baseline(settings)
    assert len([r for r in caplog.records if "none.parquet" in r.getMessage()]) == 1
    get_baseline.cache_clear()


def test_the_committed_baseline_resolves_a_real_four_digit_row() -> None:
    settings = get_plant_hours_settings()
    baseline = load_baseline(settings)
    assert baseline.release and len(baseline.hours_per_week) > 0
    code = next(iter(baseline.hours_per_week))
    got = PlantHours(baseline, settings, DEFAULT)(code + "10"[: 6 - len(code)])
    assert got.source.startswith(f"Census QPC {baseline.release}, NAICS {code}")


def test_a_boolean_is_not_hours() -> None:
    assert _valid_hours(True, get_plant_hours_settings()) is None
    assert _valid_hours("84", get_plant_hours_settings()) is None
