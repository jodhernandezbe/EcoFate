"""Scenario ``assessment-queued-then-explained``: the assessment runs as a background job.

The first reply says the work started and states no result; the follow-up turn explains the
finished result, which the job takes from the full assessment's recorded ``assess_facilities``
output (``evals/cassettes/full-assessment-with-nei-stacks.json``; nothing is copied).

Run with: ``uv run pytest -m eval tests/evals/test_background_assessment.py``
"""

from __future__ import annotations

import pytest

from evals.record import RunRecord
from evals.scenarios import BACKGROUND_ASSESSMENT
from evals.scoring import ScenarioScore
from evals.suite import cassette_path, evaluate

pytestmark = pytest.mark.eval


@pytest.fixture(scope="module")
def scored() -> tuple[RunRecord, ScenarioScore]:
    if not cassette_path(BACKGROUND_ASSESSMENT).is_file():
        pytest.skip(f"no cassette: {cassette_path(BACKGROUND_ASSESSMENT)}")
    return evaluate(BACKGROUND_ASSESSMENT)


@pytest.mark.parametrize("check", [c.name for c in BACKGROUND_ASSESSMENT.checks])
def test_check(scored: tuple[RunRecord, ScenarioScore], check: str) -> None:
    _, score = scored
    (outcome,) = [o for o in score.outcomes if o.name == check]
    assert outcome.passed, f"{check}: {outcome.reason}\n\nreport: {score.report_path}"


def test_llm_judge_complete_report(scored: tuple[RunRecord, ScenarioScore]) -> None:
    record, score = scored
    failed = [f for f in score.failures() if f.startswith("judge: ")]
    assert not failed, f"{record.report}\n\n" + "\n".join(failed)
