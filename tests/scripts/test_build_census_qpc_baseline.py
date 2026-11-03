"""End-to-end tests of scripts.build_census_qpc_baseline (in-memory workbook, fixed date)."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import httpx
import pytest

from config.qpc import QpcSettings, get_qpc_settings
from scripts.build_census_qpc_baseline import load_children, main
from scripts.qpc.output import read_rows
from tests.scripts.qpc.sheets import INTRO, data_row, sheet_rows, workbook

TODAY = date(2026, 10, 22)
SHEET = "FULL Utilization Rates"
TITLES = (
    "naics_code,naics_title,vintage\n"
    "313110,Synthetic,2022\n313210,Synthetic,2022\n315110,Old,2017\n"
)


def _book(*rows: object, title: str | None = None) -> bytes:
    sheet = sheet_rows(*rows)  # type: ignore[arg-type]
    if title:
        sheet[0] = (title,)
    return workbook({"Introduction": [(INTRO,)], SHEET: sheet})


def _client(body: bytes, seen: list[str] | None = None, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _settings() -> QpcSettings:
    return dataclasses.replace(get_qpc_settings(), min_codes=2)


def _run(tmp_path: Path, client: httpx.Client, today: date = TODAY) -> tuple[int, Path]:
    titles = tmp_path / "titles.csv"
    titles.write_text(TITLES, encoding="utf-8")
    out = tmp_path / "out" / "q.parquet"
    code = main(
        ["-o", str(out)],
        today=lambda: today,
        client=client,
        settings=_settings(),
        titles_path=titles,
    )
    return code, out


GOOD = (
    data_row("3111,7", "Group", 12.5),
    data_row("313", "Three", 33.0),
    data_row("32411", "Part", 5.0),
)


def test_builds_the_parquet_for_the_release_two_quarters_back(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[str] = []
    code, out = _run(tmp_path, _client(_book(*GOOD), seen))
    assert code == 0
    assert seen == [
        "https://www2.census.gov/programs-surveys/qpc/tables/2026/2026-qtr-table-final-q2.xlsx",
    ]
    rows = read_rows(out)
    assert [(r["naics_code"], r["avg_plant_hours_per_week"]) for r in rows] == [
        ("3111", 12.5), ("3117", 12.5), ("3131", 33.0), ("3132", 33.0),
    ]  # fmt: skip
    report = capsys.readouterr().out
    assert "wrote 4 four-digit codes" in report and "32411" in report and "only part" in report


def test_second_quarter_looks_at_the_previous_year(tmp_path: Path) -> None:
    seen: list[str] = []
    book = _book(*GOOD, title="TABLE 1. Synthetic: 2025 Quarter 4")
    code, _ = _run(tmp_path, _client(book, seen), date(2026, 5, 3))
    assert seen[0].endswith("/2025/2025-qtr-table-final-q4.xlsx")
    assert code == 1  # the synthetic block years say 2026, not 2025


def test_404_leaves_the_existing_file_alone(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "out" / "q.parquet"
    out.parent.mkdir()
    out.write_bytes(b"previous")
    code, _ = _run(tmp_path, _client(b"", status=404))
    assert code == 1 and out.read_bytes() == b"previous"
    assert "2026Q2 is not published" in capsys.readouterr().err


def test_wrong_quarter_writes_nothing(tmp_path: Path) -> None:
    code, out = _run(tmp_path, _client(_book(*GOOD, title="TABLE 1: 2026 Quarter 3")))
    assert code == 1 and not out.exists()


def test_too_few_codes_writes_nothing(tmp_path: Path) -> None:
    code, out = _run(tmp_path, _client(_book(data_row(3112, "Only", 10.0))))
    assert code == 1 and not out.exists()


def test_html_error_page_writes_nothing(tmp_path: Path) -> None:
    code, out = _run(tmp_path, _client(b"<html>down</html>"))
    assert code == 1 and not out.exists()


def test_rerun_is_identical(tmp_path: Path) -> None:
    _, first = _run(tmp_path, _client(_book(*GOOD)))
    a = read_rows(first)
    _, second = _run(tmp_path, _client(_book(*GOOD)))
    assert read_rows(second) == a


def test_children_come_from_the_configured_edition_only(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text(TITLES, encoding="utf-8")
    assert load_children(path, "naics_code", "vintage", 2022) == {"313": ("3131", "3132")}


def test_missing_titles_table_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="build_naics_titles"):
        load_children(tmp_path / "none.csv", "naics_code", "vintage", 2022)
