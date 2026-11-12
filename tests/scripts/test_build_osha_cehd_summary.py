"""Tests for scripts.build_osha_cehd_summary (tiny synthetic CSVs, never OSHA data)."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from config.osha_cehd import OshaCehdSettings, load_osha_cehd_settings
from scripts.build_osha_cehd_summary import (
    Group,
    Report,
    build_crosswalk,
    build_summary,
    cas_is_valid,
    csv_member,
    dict_rows,
    listing_rows,
    percentile,
    read_year,
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
HEADER = (
    "INSPECTION_NUMBER,SAMPLING_NUMBER,NAICS_CODE,DATE_SAMPLED,SAMPLE_TYPE,BLANK_SAMPLE,"
    "TIME_SAMPLED,IMIS_SUBSTANCE_CODE,SAMPLE_RESULT,UNIT_OF_MEASUREMENT,QUALIFIER"
)


def _row(
    sampling: str = "S1",
    naics: str = "325110",
    kind: str = "P",
    blank: str = "N",
    minutes: str = "240",
    imis: str = "AAAA",
    result: str = "2",
    unit: str = "M",
    qualifier: str = "",
    date_sampled: str = "2020-JAN-05",
) -> str:
    fields = [
        "1",
        sampling,
        naics,
        date_sampled,
        kind,
        blank,
        minutes,
        imis,
        result,
        unit,
        qualifier,
    ]
    return ",".join(fields)


def _settings(tmp_path: Path) -> OshaCehdSettings:
    text = SETTINGS_TEXT.replace("SUMMARY", str(tmp_path / "s.csv"))
    path = tmp_path / "settings.toml"
    path.write_text(text.replace("CROSSWALK", str(tmp_path / "c.csv")), encoding="utf-8")
    return load_osha_cehd_settings(path)


def _zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _read(
    tmp_path: Path,
    rows: list[str],
    header: str = HEADER,
) -> tuple[dict[tuple[str, str, str], Group], Report]:
    groups: dict[tuple[str, str, str], Group] = {}
    report = Report()
    raw = _zip({"data.csv": "\n".join([header, *rows]) + "\n"})
    read_year(raw, 2020, _settings(tmp_path), groups, report)
    return groups, report


def _summary(
    tmp_path: Path,
    rows_by_year: dict[int, list[str]],
) -> tuple[list[dict[str, str]], Report]:
    settings = _settings(tmp_path)
    archives = {
        settings.url_pattern.format(year=y): _zip({"d.csv": "\n".join([HEADER, *rows]) + "\n"})
        for y, rows in rows_by_year.items()
    }
    report = build_summary(settings, lambda url: archives[url], date(2026, 1, 2))
    lines = settings.summary_path.read_text(encoding="utf-8").splitlines()
    return list(csv.DictReader(lines[1:])), report


def test_personal_samples_only(tmp_path: Path) -> None:
    rows = [_row(sampling=f"S{k}", kind=k) for k in "PABW"]
    groups, report = _read(tmp_path, rows)
    assert len(groups) == 1
    assert report.read == 4
    assert report.kept == 1
    assert report.skipped["not a personal sample"] == 3


def test_blank_and_blank_qualifier_skipped(tmp_path: Path) -> None:
    rows = [_row(sampling="S1", blank="Y"), _row(sampling="S2", qualifier="ND-BLK")]
    groups, report = _read(tmp_path, rows)
    assert not groups
    assert report.skipped["blank sample"] == 2


def test_unit_filter_and_units_kept_apart(tmp_path: Path) -> None:
    rows = [_row(sampling="S1", unit="M"), _row(sampling="S2", unit="P"), _row(unit="X")]
    groups, report = _read(tmp_path, rows)
    assert {key[2] for key in groups} == {"mg/m^3", "ppm"}
    assert report.skipped["unit not accepted"] == 1


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"result": "abc"}, "result not a non-negative number"),
        ({"result": "-1"}, "result not a non-negative number"),
        ({"result": "nan"}, "result not a non-negative number"),
        ({"minutes": ""}, "no positive sampling time"),
        ({"minutes": "0"}, "no positive sampling time"),
        ({"imis": ""}, "no sampling number or substance code"),
    ],
)
def test_malformed_rows_counted_not_fatal(
    tmp_path: Path,
    kwargs: dict[str, str],
    reason: str,
) -> None:
    groups, report = _read(tmp_path, [_row(**kwargs), _row(sampling="S9")])
    assert len(groups) == 1
    assert report.skipped[reason] == 1


def test_short_row_counted(tmp_path: Path) -> None:
    _, report = _read(tmp_path, ["1,S1,325110", _row()])
    assert report.skipped["row too short"] == 1
    assert report.kept == 1


def test_time_weighted_collapse(tmp_path: Path) -> None:
    rows = [_row(minutes="240", result="2"), _row(minutes="120", result="8")]
    groups, _ = _read(tmp_path, rows)
    group = next(iter(groups.values()))
    assert group.weighted / group.minutes == pytest.approx(4.0)


def test_two_240_minute_samples_make_one_value(tmp_path: Path) -> None:
    out, _ = _summary(tmp_path, {2020: [_row(result="2"), _row(result="4")], 2021: []})
    row = next(r for r in out if r["naics_prefix"] == "325110")
    assert row["n"] == "1"
    assert float(row["median"]) == pytest.approx(3.0)


def test_nondetect_only_when_all_rows_nd(tmp_path: Path) -> None:
    rows = [
        _row(sampling="S1", qualifier="ND", result="0"),
        _row(sampling="S1", qualifier="ND", result="0"),
        _row(sampling="S2", qualifier="ND", result="0"),
        _row(sampling="S2", qualifier="", result="3"),
    ]
    out, _ = _summary(tmp_path, {2020: rows, 2021: []})
    row = next(r for r in out if r["naics_prefix"] == "325110")
    assert (row["n"], row["n_nd"]) == ("2", "1")


def test_statistics_and_years(tmp_path: Path) -> None:
    rows20 = [_row(sampling=f"A{i}", result=str(i)) for i in range(1, 4)]
    rows21 = [_row(sampling=f"B{i}", result=str(i), date_sampled="2021-MAR-01") for i in (4, 5)]
    out, _ = _summary(tmp_path, {2020: rows20, 2021: rows21})
    row = next(r for r in out if r["naics_prefix"] == "325110")
    assert row["n"] == "5"
    assert float(row["median"]) == 3.0
    assert float(row["p95"]) == pytest.approx(4.8)
    assert (row["first_year"], row["last_year"]) == ("2020", "2021")


def test_naics_prefix_rows_and_short_codes(tmp_path: Path) -> None:
    rows = [
        _row(sampling="S1", naics="325110"),
        _row(sampling="S2", naics="32"),
        _row(sampling="S3", naics=""),
    ]
    out, _ = _summary(tmp_path, {2020: rows, 2021: []})
    assert {r["naics_prefix"] for r in out} == {"325110", "3251", "325"}


def test_summary_comment_line(tmp_path: Path) -> None:
    _summary(tmp_path, {2020: [_row()], 2021: []})
    first = _settings(tmp_path).summary_path.read_text(encoding="utf-8").splitlines()[0]
    assert first == "# OSHA CEHD personal air samples, years 2020-2021, built 2026-01-02"


def test_pipe_delimited_quoted_bom_file(tmp_path: Path) -> None:
    header = HEADER.replace(",", "|") + ",,,"
    lines = ['"' + _row().replace(",", "|") + '"']
    groups, report = _read(tmp_path, ['"' + lines[0][1:-1] + '"'], header='﻿"' + header + '"')
    assert report.kept == 1
    assert len(groups) == 1


def test_trailing_commas_on_pipe_rows(tmp_path: Path) -> None:
    header = HEADER.replace(",", "|") + ",,,,"
    row = _row(qualifier="ND").replace(",", "|") + ",,,,"
    groups, report = _read(tmp_path, [row], header=header)
    assert report.kept == 1
    assert next(iter(groups.values())).all_nd


def test_header_missing_column_raises() -> None:
    with pytest.raises(ValueError, match="QUALIFIER"):
        list(dict_rows("SAMPLING_NUMBER,NAICS_CODE\nS1,325110\n"))


def test_zip_without_csv_member_rejected() -> None:
    with (
        zipfile.ZipFile(io.BytesIO(_zip({"data.xml": "<x/>"}))) as archive,
        pytest.raises(ValueError, match="exactly one CSV"),
    ):
        csv_member(archive)


def test_zip_with_two_csv_members_rejected() -> None:
    with (
        zipfile.ZipFile(io.BytesIO(_zip({"a.csv": "x", "b.csv": "y"}))) as archive,
        pytest.raises(ValueError, match="exactly one CSV"),
    ):
        csv_member(archive)


def test_zip_with_unexpected_member_stops_build(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one CSV"):
        build_summary(
            _settings(tmp_path),
            lambda _url: _zip({"data.xml": "<x/>"}),
            date(2026, 1, 2),
        )


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [([1.0], 0.95, 1.0), ([1.0, 2.0], 0.5, 1.5), ([1.0, 2.0, 3.0, 4.0, 5.0], 0.95, 4.8)],
)
def test_percentile_linear(values: list[float], q: float, expected: float) -> None:
    assert percentile(values, q) == pytest.approx(expected)


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError, match="no values"):
        percentile([], 0.5)


@pytest.mark.parametrize(
    ("cas", "ok"),
    [("108-88-3", True), ("71-43-2", True), ("108-88-4", False), ("abc", False), ("", False)],
)
def test_cas_check(cas: str, ok: bool) -> None:
    assert cas_is_valid(cas) is ok


def _items(codes: str) -> str:
    return "".join(f"<li>{c}</li>" for c in codes.split())


def _page(rows: list[tuple[str, str, str, str]]) -> bytes:
    cells = "".join(
        f'<tr><td><a href="/chemicaldata/{rec}" hreflang="en">{name}</a></td><td> {cas} </td>'
        f"<td><ul>{_items(codes)}</ul></td><td><p>syn</p></td></tr>"
        for rec, name, cas, codes in rows
    )
    return f"<table><tbody><tr><th>x</th></tr>{cells}</tbody></table>".encode()


def test_listing_rows_parse() -> None:
    page = _page([("7", "TOLUENE &amp; CO", "108-88-3", "AAAA BBBB")]).decode()
    assert listing_rows(page) == [("7", "TOLUENE & CO", "108-88-3", ["AAAA", "BBBB"])]


def test_crosswalk_keeps_only_clean_pairs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    pages = {
        "https://example.test/list?page=0": _page(
            [
                ("1", "TOLUENE", "108-88-3", "AAAA"),
                ("2", "NO CAS", "", "BBBB"),
                ("3", "BAD CAS", "108-88-4", "CCCC"),
                ("4", "NOTED", "71-43-2", "0005_(total);_request"),
                ("5", "DUP ONE", "75-09-2", "DDDD"),
                ("6", "DUP TWO", "71-43-2", "DDDD"),
            ],
        ),
        "https://example.test/list?page=1": _page([]),
    }
    skipped: Counter[str] = Counter()
    written = build_crosswalk(settings, lambda url: pages[url], skipped)
    lines = list(csv.DictReader(settings.crosswalk_path.read_text(encoding="utf-8").splitlines()))
    assert written == 1
    assert [(r["imis_code"], r["cas"]) for r in lines] == [("AAAA", "108-88-3")]
    assert lines[0]["source"] == "https://www.osha.gov/chemicaldata/1"
    assert skipped["no valid CAS number"] == 2
