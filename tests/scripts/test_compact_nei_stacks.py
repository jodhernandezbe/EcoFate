"""Tests for scripts.compact_nei_stacks (synthetic zips: fake IDs, round numbers)."""

from __future__ import annotations

import gzip
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from config.stack import NeiSettings, load_stack_settings
from scripts.compact_nei_stacks import (
    canonical_number,
    main,
    read_combinations,
    shard_rows,
    write_shards,
)

NEI = load_stack_settings().nei
HEADER = "FACILITY_ID,POLL,STKHGT,STKDIAM,STKTEMP,STKVEL,OTHER\n"
COMMENTS = "#FORMAT=FF10_POINT\n#YEAR=2023\n"


def _zip(tmp_path: Path, rows: str, header: str = HEADER, name: str = "flat.csv") -> Path:
    path = tmp_path / "raw.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, COMMENTS + header + rows)
    return path


def _lines(path: Path) -> list[str]:
    return gzip.decompress(path.read_bytes()).decode().splitlines()


ROWS = (
    "1000001,A,10,1,300,5,x\n"
    "1000001,B,10,1,300,5,x\n"  # another pollutant, same stack
    "1000001,C,10.0,1.0,300,5.0,x\n"  # same numbers written differently
    "1000001,A,20,2,400,6,x\n"  # second stack
    "2000002,A,30,3,500,7,x\n"
    "12,A,40,4,600,8,x\n"
)


def test_canonical_number() -> None:
    assert [canonical_number(t) for t in ("23", "23.0", " 2.67 ", "1e2")] == [
        "23",
        "23",
        "2.67",
        "100",
    ]


@pytest.mark.parametrize("text", ["", " ", "abc", "0", "-1", "nan", "inf", "-inf"])
def test_canonical_number_rejects(text: str) -> None:
    assert canonical_number(text) is None


def test_pollutant_rows_collapse(tmp_path: Path) -> None:
    found = read_combinations(_zip(tmp_path, ROWS), NEI)
    assert found["1000001"] == {("10", "1", "5", "300"), ("20", "2", "6", "400")}
    assert found["2000002"] == {("30", "3", "7", "500")}


def test_columns_follow_quantity_order(tmp_path: Path) -> None:
    """Combinations are (height, diameter, velocity, temperature), not the raw file's order."""
    found = read_combinations(_zip(tmp_path, "1000001,A,10,1,300,5,x\n"), NEI)
    assert found["1000001"] == {("10", "1", "5", "300")}


@pytest.mark.parametrize(
    "row",
    [
        "abc1,A,10,1,300,5,x\n",  # id not digits
        ",A,10,1,300,5,x\n",  # blank id
        "1000001,A,,1,300,5,x\n",  # blank height
        "1000001,A,10,0,300,5,x\n",  # zero diameter
        "1000001,A,10,1,-5,5,x\n",  # negative temperature
        "1000001,A,10,1,300,nan,x\n",  # not finite
        "1000001,A,10,1,300\n",  # short row
    ],
)
def test_invalid_rows_are_dropped(tmp_path: Path, row: str) -> None:
    assert read_combinations(_zip(tmp_path, row + "2000002,A,30,3,500,7,x\n"), NEI) == {
        "2000002": {("30", "3", "7", "500")},
    }


def test_comment_lines_and_bom_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "raw.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.csv", "﻿" + HEADER + "1000001,A,10,1,300,5,x\n")
    assert list(read_combinations(path, NEI)) == ["1000001"]


def test_missing_column_raises(tmp_path: Path) -> None:
    path = _zip(tmp_path, ROWS, header=HEADER.replace("STKVEL", "VEL"))
    with pytest.raises(ValueError, match="STKVEL"):
        read_combinations(path, NEI)


def test_zip_without_csv_raises(tmp_path: Path) -> None:
    path = _zip(tmp_path, ROWS, name="notes.txt")
    with pytest.raises(ValueError, match="no CSV"):
        read_combinations(path, NEI)


def test_shards_are_named_by_leading_digits_and_sorted(tmp_path: Path) -> None:
    found = read_combinations(_zip(tmp_path, ROWS), NEI)
    assert shard_rows(found, 1) == {
        "1": [
            ["1000001", "10", "1", "5", "300"],
            ["1000001", "20", "2", "6", "400"],
            ["12", "40", "4", "8", "600"],
        ],
        "2": [["2000002", "30", "3", "7", "500"]],
    }
    assert set(shard_rows(found, 2)) == {"10", "20", "12"}


def test_numeric_sort_not_text_sort() -> None:
    found = {"1000001": {("9", "1", "5", "300"), ("10", "1", "5", "300")}}
    assert [r[1] for r in shard_rows(found, 1)["1"]] == ["9", "10"]


def _settings(tmp_path: Path) -> NeiSettings:
    return replace(NEI, directory=tmp_path / "out", raw_path=tmp_path / "raw.zip")


def test_main_writes_shards_with_configured_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip_path = _zip(tmp_path, ROWS)
    settings = replace(load_stack_settings(), nei=_settings(tmp_path))
    monkeypatch.setattr("scripts.compact_nei_stacks.get_stack_settings", lambda: settings)
    assert main([]) == 0
    one = tmp_path / "out" / "nei_stacks_1.csv.gz"
    assert _lines(one)[:2] == ["eis_id,stkhgt,stkdiam,stkvel,stktemp", "1000001,10,1,5,300"]
    assert zip_path.exists()


def test_output_is_reproducible(tmp_path: Path) -> None:
    found = read_combinations(_zip(tmp_path, ROWS), NEI)
    shards = shard_rows(found, 1)
    first = write_shards(shards, _settings(tmp_path), tmp_path / "a")
    second = write_shards(shards, _settings(tmp_path), tmp_path / "b")
    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]


def test_stale_shards_are_removed_but_other_files_kept(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "nei_stacks_9.csv.gz").write_bytes(b"old")
    (out / "README.txt").write_text("keep")
    write_shards({"1": [["1000001", "10", "1", "5", "300"]]}, _settings(tmp_path), out)
    assert not (out / "nei_stacks_9.csv.gz").exists()
    assert (out / "README.txt").read_text() == "keep"


@pytest.mark.parametrize("rows", ["", "abc,A,10,1,300,5,x\n"])
def test_main_with_no_usable_rows_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: str,
) -> None:
    zip_path = _zip(tmp_path, rows)
    settings = replace(load_stack_settings(), nei=_settings(tmp_path))
    monkeypatch.setattr("scripts.compact_nei_stacks.get_stack_settings", lambda: settings)
    assert main([str(zip_path)]) == 1
    assert not (tmp_path / "out").exists()


def test_main_reports_missing_and_bad_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = replace(load_stack_settings(), nei=_settings(tmp_path))
    monkeypatch.setattr("scripts.compact_nei_stacks.get_stack_settings", lambda: settings)
    assert main([str(tmp_path / "absent.zip")]) == 1
    (tmp_path / "bad.zip").write_bytes(b"not a zip")
    assert main([str(tmp_path / "bad.zip")]) == 1
    assert "cannot compact the NEI stacks" in capsys.readouterr().err
