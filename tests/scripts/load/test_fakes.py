"""Tests for scripts/load/fakes.py: timings, the recorded assessment and the fake job."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from commons.stop import StoppedError
from scripts.load.fakes import (
    JOB_OVERRIDE,
    Recorded,
    fake_job,
    load_recorded,
    load_timings,
)

JobRunner = Callable[[dict[str, object], Callable[[], bool]], tuple[object, object]]


def _toml(tmp_path: Path, model: str = "1", pre: str = "2", job: str = "3") -> Path:
    path = tmp_path / "timings.toml"
    path.write_text(
        f"model_seconds = {model}\npreflight_seconds = {pre}\njob_seconds = {job}\n",
        encoding="utf-8",
    )
    return path


def test_load_timings_reads_file(tmp_path: Path) -> None:
    timings = load_timings(_toml(tmp_path), environ={})
    assert (timings.model_seconds, timings.preflight_seconds, timings.job_seconds) == (1, 2, 3)


def test_job_override_from_environ(tmp_path: Path) -> None:
    timings = load_timings(_toml(tmp_path), environ={JOB_OVERRIDE: "7"})
    assert timings.job_seconds == 7
    assert timings.model_seconds == 1


def test_blank_override_is_ignored(tmp_path: Path) -> None:
    assert load_timings(_toml(tmp_path), environ={JOB_OVERRIDE: "  "}).job_seconds == 3


def test_negative_value_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0 and 3600"):
        load_timings(_toml(tmp_path, model="-1"), environ={})


def test_too_large_value_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0 and 3600"):
        load_timings(_toml(tmp_path, job="3600"), environ={})


def test_override_out_of_range_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0 and 3600"):
        load_timings(_toml(tmp_path), environ={JOB_OVERRIDE: "-5"})


def test_load_recorded_reads_shipped_file() -> None:
    recorded = load_recorded()
    assert "cas_number" in recorded.args
    assert recorded.view


def _runner(seconds: float) -> JobRunner:
    recorded = Recorded(args={}, view={"marker": "view"})
    return cast(JobRunner, fake_job(seconds, recorded))


def test_fake_job_zero_seconds_returns_view_and_empty() -> None:
    assert _runner(0)({}, lambda: False) == ({"marker": "view"}, {})


def test_fake_job_raises_when_asked_to_stop() -> None:
    with pytest.raises(StoppedError):
        _runner(0.05)({}, lambda: True)


def test_fake_job_runs_to_the_end_when_not_stopped() -> None:
    assert _runner(0.05)({}, lambda: False) == ({"marker": "view"}, {})
