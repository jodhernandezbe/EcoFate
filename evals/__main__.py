"""Command line for agent evaluations.

uv run python -m evals record <scenario>   # run live, save the cassette
uv run python -m evals record-extra <scenario>  # only its extra calls, added to the cassette
uv run python -m evals run [<scenario> ...]  # replay, score, write reports
uv run python -m evals catalogue  # every catalogue question live; answers, time, tokens, cost
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from app.telemetry import configure_telemetry
from config.evaluation import get_evaluation_settings
from config.telemetry import get_telemetry_settings
from evals.catalogue.run import run_from_settings
from evals.scenarios import CATALOGUE, scenario
from evals.scoring import new_run_dir
from evals.suite import cassette_path, evaluate, record_extra_live, record_live


def _record(scenario_id: str) -> int:
    record = record_live(scenario(scenario_id))
    print(f"recorded {len(record.calls)} tool calls to {cassette_path(scenario(scenario_id))}")
    print(f"run completed: {record.completed} {record.error or ''}")
    return 0


def _record_extra(scenario_id: str) -> int:
    count = record_extra_live(scenario(scenario_id))
    print(f"recorded {count} extra calls into {cassette_path(scenario(scenario_id))}")
    return 0


def _run(scenario_ids: list[str]) -> int:
    chosen = [scenario(i) for i in scenario_ids] or [s for s in CATALOGUE if not s.blocked]
    run_dir = new_run_dir(get_evaluation_settings())
    failed = 0
    for item in chosen:
        if item.blocked:
            print(f"SKIP {item.id}: {item.blocked}")
            continue
        _, score = evaluate(item, run_dir)
        failed += not score.passed
        print(f"{'PASS' if score.passed else 'FAIL'} {item.id}")
        for failure in score.failures():
            print(f"    {failure}")
    print(f"reports: {run_dir}")
    return 1 if failed else 0


def _catalogue() -> int:
    configure_telemetry(get_telemetry_settings())  # after load_dotenv: reads the Logfire token
    run_from_settings()
    return 0


def main() -> int:
    """Parse the command and run it; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m evals", description="Agent evaluations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("record", help="run live and save the cassette").add_argument("scenario")
    extra = commands.add_parser("record-extra", help="record only the extra calls, keep the rest")
    extra.add_argument("scenario")
    run = commands.add_parser("run", help="replay, score and report")
    run.add_argument("scenarios", nargs="*", help="scenario ids (default: all unblocked)")
    commands.add_parser("catalogue", help="run every catalogue question through the live agent")
    args = parser.parse_args()
    load_dotenv()
    if args.command == "record":
        return _record(args.scenario)
    if args.command == "record-extra":
        return _record_extra(args.scenario)
    if args.command == "catalogue":
        return _catalogue()
    return _run(args.scenarios)


if __name__ == "__main__":
    raise SystemExit(main())
