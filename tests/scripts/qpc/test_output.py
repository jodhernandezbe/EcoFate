"""Tests for scripts.qpc.output."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.qpc.output import Provenance, read_metadata, read_rows, write_baseline
from scripts.qpc.release import Release
from scripts.qpc.table import Entry, Extraction

RELEASE = Release(2026, 2)
INFO = Provenance("https://h/x.xlsx", "ab" * 32, "2026-10-22", 2022, "Sheet")
EXTRACTION = Extraction(
    (
        Entry("3117,8", "Group", 12.5, ("3118", "3117")),
        Entry("3112", "Single", 168.0, ("3112",)),
    ),
    (),
)


def test_one_row_per_code_sorted_with_release(tmp_path: Path) -> None:
    out = tmp_path / "q.parquet"
    write_baseline(EXTRACTION, RELEASE, INFO, out)
    rows = read_rows(out)
    assert [r["naics_code"] for r in rows] == ["3112", "3117", "3118"]
    assert {(r["release_year"], r["release_quarter"]) for r in rows} == {(2026, 2)}
    assert rows[1]["source_naics"] == "3117,8" and rows[1]["avg_plant_hours_per_week"] == 12.5


def test_metadata_records_the_release(tmp_path: Path) -> None:
    out = tmp_path / "q.parquet"
    write_baseline(EXTRACTION, RELEASE, INFO, out)
    meta = read_metadata(out)
    assert meta["qpc.release"] == "2026Q2"
    assert meta["qpc.url"] == INFO.url and meta["qpc.sha256"] == INFO.sha256
    assert meta["qpc.naics_edition"] == "2022" and meta["qpc.retrieved"] == "2026-10-22"


def test_rerun_gives_identical_rows(tmp_path: Path) -> None:
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    write_baseline(EXTRACTION, RELEASE, INFO, a)
    write_baseline(EXTRACTION, RELEASE, INFO, b)
    assert read_rows(a) == read_rows(b)


def test_failed_write_keeps_the_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "q.parquet"
    write_baseline(EXTRACTION, RELEASE, INFO, out)
    before = out.read_bytes()

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("scripts.qpc.output.pq.write_table", boom)
    with pytest.raises(OSError, match="disk full"):
        write_baseline(EXTRACTION, RELEASE, INFO, out)
    assert out.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["q.parquet"]
