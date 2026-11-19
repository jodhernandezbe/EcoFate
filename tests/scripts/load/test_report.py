"""Tests for scripts/load/report.py: percentiles, summaries, shares and the written report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.load.report import (
    DURATIONS,
    Measurements,
    markdown,
    percentile,
    shares,
    summary,
    write,
)

NO_RESOURCES: dict[str, dict[str, float]] = {}


def test_percentile_nearest_rank() -> None:
    values = [4.0, 1.0, 3.0, 2.0]
    assert percentile(values, 0.5) == 2.0
    assert percentile(values, 0.95) == 4.0
    assert percentile(values, 0.0) == 1.0


def test_percentile_single_value() -> None:
    assert percentile([9.0], 0.95) == 9.0


def test_summary_none_for_empty() -> None:
    assert summary([]) is None


def test_summary_fields() -> None:
    assert summary([1.0, 2.0, 3.0]) == {"n": 3, "median": 2.0, "p95": 3.0, "max": 3.0}


def test_shares_zero_requests() -> None:
    assert shares({}, 0) == {"409": 0.0, "429": 0.0, "5xx": 0.0}


def test_shares_counts_409_429_and_5xx() -> None:
    result = shares({"200": 5, "409": 2, "429": 1, "500": 1, "503": 1}, 10)
    assert result == {"409": 0.2, "429": 0.1, "5xx": 0.2}


def test_time_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown measurement"):
        Measurements().time("nope", 1.0)


def test_time_and_answered_record() -> None:
    measured = Measurements()
    measured.time("job_duration", 1.0)
    measured.answered(200)
    measured.answered(200)
    assert measured.durations == {"job_duration": [1.0]}
    assert measured.statuses == {"200": 2}
    assert measured.requests == 2


def test_markdown_shows_not_measured_for_absent() -> None:
    page = markdown("Title", Measurements(), NO_RESOURCES)
    assert page.count("not measured") == len(DURATIONS)
    assert "### Title" in page


def test_markdown_budget_line_only_when_needed() -> None:
    assert "Estimated model cost" not in markdown("t", Measurements(), NO_RESOURCES)
    with_cost = markdown("t", Measurements(cost_usd=1.5), NO_RESOURCES)
    assert "Estimated model cost: USD 1.50." in with_cost
    assert "budget cap" not in with_cost
    reached = markdown("t", Measurements(budget_reached=True), NO_RESOURCES)
    assert "The budget cap ended the run." in reached


def test_markdown_resource_rows() -> None:
    resources = {"api": {"cpu_peak": 50.0, "cpu_mean": 20.0, "mem_peak_mib": 128.0}}
    assert "| api | 50 | 20 | 128 |" in markdown("t", Measurements(), resources)


def test_write_creates_both_files(tmp_path: Path) -> None:
    measured = Measurements()
    measured.time("job_duration", 2.0)
    page = write(tmp_path / "out" / "run", "Title", measured, NO_RESOURCES)
    assert page.name == "summary.md"
    assert page.read_text(encoding="utf-8").startswith("### Title")
    raw = json.loads((page.parent / "measurements.json").read_text(encoding="utf-8"))
    assert raw["measurements"]["durations"] == {"job_duration": [2.0]}
