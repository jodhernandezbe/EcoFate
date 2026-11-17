"""Run catalogue scenarios: replay and score them, or record them from the live services.

The agent's model is always the program's (``[agent]``, built by ``app.chat_model``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from langchain_core.tools import BaseTool

from app.chat_model import build_chat_model
from config.agent import get_agent_settings
from config.evaluation import get_evaluation_settings
from evals.cassette import Cassette, Recorder, replay_tools
from evals.record import RunRecord
from evals.runner import run_scenario
from evals.scenarios import Scenario
from evals.scoring import ScenarioScore, new_run_dir, score_run
from tools.registry import get_all_tools


def cassette_path(scenario: Scenario) -> Path:
    """Where the recordings of ``scenario`` live."""
    return get_evaluation_settings().cassette_dir / f"{scenario.id}.json"


def run_with(scenario: Scenario, tools: Sequence[BaseTool]) -> RunRecord:
    """Run ``scenario`` with the program's chat model and step limit over ``tools``."""
    settings = get_agent_settings()
    return run_scenario(
        build_chat_model(settings),
        tools,
        (scenario.id, scenario.query),
        settings,
        follow_up=scenario.follow_up,
    )


def replayed(scenario: Scenario) -> RunRecord:
    """Run ``scenario`` with network tools replayed from its cassette."""
    cassette = Cassette.load(cassette_path(scenario))
    live = get_evaluation_settings().live_tools
    return run_with(scenario, replay_tools(get_all_tools(), cassette, live))


def evaluate(scenario: Scenario, run_dir: Path | None = None) -> tuple[RunRecord, ScenarioScore]:
    """Replay ``scenario``, score it with its checks and judges, write its report."""
    settings = get_evaluation_settings()
    record = replayed(scenario)
    folder = run_dir if run_dir is not None else new_run_dir(settings)
    return record, score_run(record, scenario.checks, scenario.judges, settings, folder)


def record_extras(scenario: Scenario, recorder: Recorder, tools: Sequence[BaseTool]) -> None:
    """Make the scenario's extra calls live through the recording ``tools``."""
    for extra in scenario.extra_calls:
        recorder.invoke(tools, extra.tool, extra.args)


def record_live(scenario: Scenario) -> RunRecord:
    """Run ``scenario`` against the live services and save every network tool output.

    The cassette is replaced by this run's recordings plus the scenario's extra calls.
    """
    recorder = Recorder()
    tools = recorder.wrap(get_all_tools(), get_evaluation_settings().live_tools)
    record = run_with(scenario, tools)
    record_extras(scenario, recorder, tools)
    recorder.save(cassette_path(scenario))
    return record


def record_extra_live(scenario: Scenario) -> int:
    """Make only the scenario's extra calls live and add them to its cassette.

    Returns:
        The number of extra calls made.
    """
    recorder = Recorder()
    recorder.seed(cassette_path(scenario))
    tools = recorder.wrap(get_all_tools(), get_evaluation_settings().live_tools)
    record_extras(scenario, recorder, tools)
    recorder.save(cassette_path(scenario))
    return len(scenario.extra_calls)
