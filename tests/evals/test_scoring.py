"""Tests for the Evidently adapter with deterministic checks only (no judge model is called)."""

from __future__ import annotations

from pathlib import Path

from config.evaluation import EvaluationSettings
from evals import checks as c
from evals.record import RunRecord, ToolCall
from evals.scoring import score_run


def _settings(tmp_path: Path) -> EvaluationSettings:
    return EvaluationSettings(
        "openai",
        "unused-judge",
        "UNUSED_KEY_VAR",
        (),
        tmp_path,
        tmp_path,
        tmp_path / "scenarios.csv",
        "catalogue.json",
        "labels.json",
        "judged.json",
        30.0,
        None,
    )


def test_checks_become_outcomes_and_a_report(tmp_path: Path) -> None:
    record = RunRecord("demo", "q", (ToolCall("t", {}, {}, unrecorded=False),), "done", None)
    checks = (c.completed(), c.no_tool_called())
    score = score_run(record, checks, (), _settings(tmp_path), tmp_path / "run")
    assert [(o.name, o.passed) for o in score.outcomes] == [
        ("run completed", True),
        ("no tool called", False),
    ]
    assert not score.passed
    assert score.failures() == ["no tool called: tools called: t({})"]
    assert score.report_path == tmp_path / "run" / "demo.html"
    assert score.report_path.is_file()


def test_all_checks_passing(tmp_path: Path) -> None:
    record = RunRecord("ok", "q", (), "done", None)
    score = score_run(record, (c.completed(),), (), _settings(tmp_path), tmp_path)
    assert score.passed
