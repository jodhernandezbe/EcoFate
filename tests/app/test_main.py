"""Tests for the command line entry point: answer on stdout, usage and cost on stderr."""

from __future__ import annotations

import sys

import pytest

from app import __main__ as cli
from app.run import RunResult
from app.usage_meter import CallUsage
from config.agent import get_agent_settings
from config.telemetry import TelemetrySettings


def test_the_answer_goes_to_stdout_and_the_cost_summary_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = get_agent_settings().model
    calls = (CallUsage(model, 1000, 0, 100), CallUsage(model, 500, 0, 50))

    def run(question: str) -> RunResult:
        return RunResult(f"answer to {question}", calls)

    monkeypatch.setattr(cli, "ask", run)
    monkeypatch.setattr(sys, "argv", ["app", "Assess CAS 71-43-2"])
    cli.main()
    out, err = capsys.readouterr()
    assert out == "answer to Assess CAS 71-43-2\n"
    assert err.startswith("Usage: 2 model calls, 1,500 input tokens")
    assert "Estimated cost: $" in err


def test_monitoring_is_configured_before_the_agent_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def configure(settings: TelemetrySettings) -> None:
        order.append("monitoring")

    def run(question: str) -> RunResult:
        order.append("ask")
        return RunResult("a", ())

    monkeypatch.setattr(cli, "load_dotenv", lambda: order.append("env"))
    monkeypatch.setattr(cli, "configure_telemetry", configure)
    monkeypatch.setattr(cli, "ask", run)
    monkeypatch.setattr(sys, "argv", ["app", "q"])
    cli.main()
    assert order == ["env", "monitoring", "ask"]
