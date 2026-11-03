"""Evidently adapter: score run records with deterministic checks and LLM judges.

Only this module imports ``evidently``. Each scenario becomes a one-row dataset: every check
result is a ``PASS``/``FAIL`` column with its reason and an Evidently test, every judge an OpenAI
binary-classification descriptor with its reasoning and a test, and a test summary gives the
verdict. Each run writes one HTML report per scenario into a time-stamped folder.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import openai
import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.core.datasets import Descriptor
from evidently.descriptors import ColumnTest, LLMEval, TestSummary
from evidently.llm.templates import BinaryClassificationPromptTemplate
from evidently.presets import TextEvals
from evidently.tests import eq

from config.evaluation import EvaluationSettings
from evals.checks import Check
from evals.judges import Judge
from evals.record import RunRecord

PASS_LABEL = "PASS"  # nosec B105 - a check or judge category, not a secret
FAIL_LABEL = "FAIL"
_REPORT = "report"
_CHECK = "check: "
_JUDGE = "judge: "
_REASON = " reason"


@dataclass(frozen=True)
class Outcome:
    """One check or judge result for a scenario."""

    name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class ScenarioScore:
    """Every outcome of one scenario run and where its report was written."""

    scenario_id: str
    outcomes: tuple[Outcome, ...]
    report_path: Path

    @property
    def passed(self) -> bool:
        """True when every check and judge passed."""
        return all(o.passed for o in self.outcomes)

    def failures(self) -> list[str]:
        """``name: reason`` of each failed outcome."""
        return [f"{o.name}: {o.reason}" for o in self.outcomes if not o.passed]


def _judge_descriptors(judge: Judge, settings: EvaluationSettings) -> list[Descriptor]:
    """The judge descriptor (verdict and reasoning columns) and a test on its verdict."""
    template = BinaryClassificationPromptTemplate(
        criteria=judge.criteria,
        target_category=PASS_LABEL,
        non_target_category=FAIL_LABEL,
        uncertainty="non_target",  # type: ignore[arg-type]
        include_reasoning=True,
    )
    column = _JUDGE + judge.name
    evaluation = LLMEval(
        _REPORT,
        provider=settings.judge_provider,
        model=settings.judge_model,
        template=template,
        alias=column,
    )
    return [evaluation, ColumnTest(column, eq(PASS_LABEL), alias=f"{column} test")]


def _check_columns(record: RunRecord, checks: Sequence[Check]) -> dict[str, list[str]]:
    columns: dict[str, list[str]] = {}
    for check in checks:
        result = check.evaluate(record)
        columns[_CHECK + check.name] = [PASS_LABEL if result.passed else FAIL_LABEL]
        columns[_CHECK + check.name + _REASON] = [result.reason]
    return columns


def _dataset(record: RunRecord, checks: Sequence[Check], judges: Sequence[Descriptor]) -> Dataset:
    columns = _check_columns(record, checks)
    frame = pd.DataFrame({"query": [record.query], _REPORT: [record.report], **columns})
    verdicts = [name for name in columns if not name.endswith(_REASON)]
    reasons = [name for name in columns if name.endswith(_REASON)]
    tests = [ColumnTest(c, eq(PASS_LABEL), alias=f"{c} test") for c in verdicts]
    summary = TestSummary(success_all=True, alias="all tests passed")
    definition = DataDefinition(
        text_columns=["query", _REPORT, *reasons],
        categorical_columns=verdicts,
    )
    descriptors: list[Descriptor] = [*tests, *judges, summary]
    return Dataset.from_pandas(frame, data_definition=definition, descriptors=descriptors)


def _check_outcomes(row: Mapping[str, object], checks: Sequence[Check]) -> list[Outcome]:
    return [
        Outcome(
            c.name,
            row.get(_CHECK + c.name) == PASS_LABEL,
            str(row.get(_CHECK + c.name + _REASON)),
        )
        for c in checks
    ]


def _judge_outcomes(
    row: Mapping[str, object],
    judges: Sequence[Judge],
    error: str | None,
) -> list[Outcome]:
    if error is not None:
        return [Outcome(_JUDGE + j.name, False, error) for j in judges]
    return [
        Outcome(
            _JUDGE + j.name,
            row.get(_JUDGE + j.name) == PASS_LABEL,
            str(row.get(f"{_JUDGE}{j.name} reasoning") or "the judge returned no verdict"),
        )
        for j in judges
    ]


def _scored_dataset(
    record: RunRecord,
    checks: Sequence[Check],
    judges: Sequence[Judge],
    settings: EvaluationSettings,
) -> tuple[Dataset, str | None]:
    """Build the dataset; if the judge cannot be reached, score the checks alone."""
    try:
        descriptors = [d for j in judges for d in _judge_descriptors(j, settings)]
        return _dataset(record, checks, descriptors), None
    except openai.OpenAIError as exc:
        return _dataset(record, checks, []), f"judge unavailable ({type(exc).__name__}: {exc})"


def score_run(
    record: RunRecord,
    checks: Sequence[Check],
    judges: Sequence[Judge],
    settings: EvaluationSettings,
    run_dir: Path,
) -> ScenarioScore:
    """Score one record, write its HTML report into ``run_dir``, return every outcome.

    A judge that cannot be reached fails with the error as its reason (fail closed).
    """
    dataset, judge_error = _scored_dataset(record, checks, judges, settings)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{record.scenario_id}.html"
    Report([TextEvals()]).run(dataset).save_html(str(path))
    frame = dataset.as_dataframe()
    row: dict[str, object] = frame.to_dict(orient="records")[0]  # type: ignore[assignment]
    outcomes = _check_outcomes(row, checks) + _judge_outcomes(row, judges, judge_error)
    return ScenarioScore(record.scenario_id, tuple(outcomes), path)


def new_run_dir(settings: EvaluationSettings) -> Path:
    """A fresh time-stamped folder under the configured report directory."""
    return settings.report_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
