"""Run catalogue scenarios: replay and score them, or record them from the live services.

The agent's model is always the program's (``[agent]``, built by ``app.chat_model``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from langchain_core.tools import BaseTool

from agent.graph import turn_tools
from app.chat_model import build_chat_model
from config.agent import get_agent_settings
from config.evaluation import get_evaluation_settings
from evals.cassette import Cassette, Recorder, replay_tools
from evals.checks import ASSESSMENT
from evals.record import RunRecord
from evals.runner import run_scenario
from evals.scenarios import Scenario
from evals.scoring import ScenarioScore, new_run_dir, score_run


def cassette_path(scenario: Scenario) -> Path:
    """Where the recordings of ``scenario`` live."""
    return get_evaluation_settings().cassette_dir / f"{scenario.cassette_id or scenario.id}.json"


def run_with(
    scenario: Scenario,
    tools: Sequence[BaseTool],
    cassette: Cassette | None = None,
) -> RunRecord:
    """Run ``scenario`` with the program's chat model and step limit over ``tools``.

    ``cassette`` is what a background scenario's job "runs" from (see ``evals/jobs.py``).
    """
    settings = get_agent_settings()
    return run_scenario(
        build_chat_model(settings),
        tools,
        (scenario.id, scenario.query),
        settings,
        follow_up=scenario.follow_up,
        background=scenario.background,
        cassette=cassette,
    )


def replayed(scenario: Scenario) -> RunRecord:
    """Run ``scenario`` with network tools replayed from its cassette."""
    cassette = Cassette.load(cassette_path(scenario))
    live = set(get_evaluation_settings().live_tools)
    if scenario.background:  # the submitter stays: it queues the job, the cassette ends it
        live.add(ASSESSMENT)
    # The tools a turn of the program gets: the job-status tool only where a job can exist.
    tools = turn_tools(has_jobs=scenario.background)
    return run_with(scenario, replay_tools(tools, cassette, live), cassette)


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


def _own_cassette(scenario: Scenario) -> None:
    """Recording writes the scenario's own cassette; one that replays another's has none."""
    if scenario.cassette_id is not None:
        raise ValueError(f"{scenario.id} replays another scenario's cassette; record that one")


def record_live(scenario: Scenario) -> RunRecord:
    """Run ``scenario`` against the live services and save every network tool output.

    The cassette is replaced by this run's recordings plus the scenario's extra calls.
    """
    _own_cassette(scenario)
    recorder = Recorder()
    tools = recorder.wrap(turn_tools(has_jobs=False), get_evaluation_settings().live_tools)
    # Recorded with no job system, so a background scenario's heavy call runs and is recorded.
    record = run_with(replace(scenario, background=False), tools)
    record_extras(scenario, recorder, tools)
    recorder.save(cassette_path(scenario))
    return record


def record_extra_live(scenario: Scenario) -> int:
    """Make only the scenario's extra calls live and add them to its cassette.

    Returns:
        The number of extra calls made.
    """
    _own_cassette(scenario)
    recorder = Recorder()
    recorder.seed(cassette_path(scenario))
    tools = recorder.wrap(turn_tools(has_jobs=False), get_evaluation_settings().live_tools)
    record_extras(scenario, recorder, tools)
    recorder.save(cassette_path(scenario))
    return len(scenario.extra_calls)
