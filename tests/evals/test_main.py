"""The evaluation command line parses its subcommands without running the agent."""

from __future__ import annotations

from pathlib import Path

import pytest

import evals.__main__ as cli


def test_catalogue_subcommand_runs_the_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def telemetry(_settings: object) -> None:
        seen.append("telemetry")

    def run() -> Path:
        seen.append("run")
        return Path("x")

    monkeypatch.setattr(cli, "configure_telemetry", telemetry)
    monkeypatch.setattr(cli, "run_from_settings", run)
    monkeypatch.setattr("sys.argv", ["evals", "catalogue"])
    assert cli.main() == 0
    assert seen == ["telemetry", "run"]


def test_catalogue_subcommand_takes_no_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["evals", "catalogue", "extra"])
    with pytest.raises(SystemExit):
        cli.main()


def test_judge_subcommand_passes_the_run_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []

    def judge(run_dir: Path) -> Path:
        seen.append(run_dir)
        return run_dir / "judged.json"

    monkeypatch.setattr(cli, "judge_run", judge)
    monkeypatch.setattr("sys.argv", ["evals", "judge", "evals/reports/x"])
    assert cli.main() == 0
    assert seen == [Path("evals/reports/x")]


def test_judge_subcommand_requires_the_run_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["evals", "judge"])
    with pytest.raises(SystemExit):
        cli.main()
