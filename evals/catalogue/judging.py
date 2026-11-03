"""Judge one catalogue run against its human labels and report the agreement.

Reads the run's results and labels (validated at the boundary, matched row for row), judges
every answer, writes the verdicts next to the results and prints the metrics and every
disagreement. The judge is injectable so the flow is tested without a model.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from config.evaluation import EvaluationSettings, get_evaluation_settings
from evals.catalogue.judge import Answer, Judge, JudgeResult, build_judge, judge_rows
from evals.catalogue.metrics import BAD, GOOD, Labelled, format_report

Progress = Callable[[str], None]


def _items(path: Path) -> list[dict[str, object]]:
    """The JSON array of objects in ``path``; raises ``ValueError`` on any other shape."""
    data = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must hold a JSON array")
    items = cast(list[object], data)
    if not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{path.name} must hold JSON objects only")
    return [cast(dict[str, object], item) for item in items]


def _text(item: dict[str, object], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{where}: {key} must be a string")
    return value


def _optional_text(item: dict[str, object], key: str, where: str) -> str | None:
    value = item.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{where}: {key} must be a string or null")
    return value


def _optional_count(item: dict[str, object], key: str, where: str) -> int | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where}: {key} must be a non-negative integer or null")
    return value


def load_answers(path: Path) -> tuple[Answer, ...]:
    """The answers of a run's results file, in order; the row position is the index."""
    return tuple(
        Answer(
            i,
            _text(item, "question", f"{path.name}[{i}]"),
            _text(item, "output", f"{path.name}[{i}]"),
        )
        for i, item in enumerate(_items(path))
    )


def _label(item: dict[str, object], where: str) -> HumanLabel:
    label = _text(item, "label", where)
    if label not in (GOOD, BAD):
        raise ValueError(f"{where}: label must be '{GOOD}' or '{BAD}'")
    index = item.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError(f"{where}: index must be an integer")
    return HumanLabel(
        index,
        _text(item, "question", where),
        label,
        _optional_text(item, "failure", where),
        _optional_count(item, "bad_votes", where),
    )


class HumanLabel:
    """One row's human label, as read from the labels file."""

    __slots__ = ("bad_votes", "failure", "index", "label", "question")

    def __init__(
        self,
        index: int,
        question: str,
        label: str,
        failure: str | None,
        bad_votes: int | None,
    ) -> None:
        self.index = index
        self.question = question
        self.label = label
        self.failure = failure
        self.bad_votes = bad_votes


def load_labels(path: Path) -> tuple[HumanLabel, ...]:
    """The human labels of a run, in file order.

    Raises:
        FileNotFoundError: If the labels file is missing.
        ValueError: If a row lacks an integer index, a question, or a good/bad label.
    """
    if not path.is_file():
        raise FileNotFoundError(f"no human labels at {path}")
    return tuple(_label(item, f"{path.name}[{i}]") for i, item in enumerate(_items(path)))


def check_match(answers: Sequence[Answer], labels: Sequence[HumanLabel]) -> None:
    """Every answer must have the label of the same index and question, and nothing more."""
    if len(answers) != len(labels):
        raise ValueError(f"{len(answers)} answers but {len(labels)} labels")
    for answer, label in zip(answers, labels, strict=True):
        if answer.index != label.index or answer.question != label.question:
            raise ValueError(f"row {answer.index}: the label's index or question does not match")


def _labelled(label: HumanLabel, result: JudgeResult) -> Labelled:
    return Labelled(
        index=label.index,
        question=label.question,
        human_label=label.label,
        human_failure=label.failure,
        bad_votes=label.bad_votes,
        judge_label=result.label,
        judge_failure=result.failure,
        reasoning=result.reasoning,
        error=result.error,
    )


def to_json(rows: Sequence[Labelled]) -> str:
    """The judged rows as one JSON array, in run order."""
    return json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False)


def judge_run(
    run_dir: Path,
    judge: Judge | None = None,
    settings: EvaluationSettings | None = None,
    progress: Progress = print,
) -> Path:
    """Judge the run in ``run_dir`` against its labels; write the verdicts; print the report.

    The labels are checked against the results before any judge call; the judge model is
    built only after that (so a missing key or a mismatch stops the command early).
    """
    chosen_settings = settings if settings is not None else get_evaluation_settings()
    answers = load_answers(run_dir / chosen_settings.catalogue_results)
    labels = load_labels(run_dir / chosen_settings.catalogue_labels)
    check_match(answers, labels)
    chosen_judge = judge if judge is not None else build_judge(chosen_settings)
    results = judge_rows(answers, chosen_judge, progress)
    rows = tuple(_labelled(label, r) for label, r in zip(labels, results, strict=True))
    out = run_dir / chosen_settings.catalogue_judged
    out.write_text(to_json(rows), encoding="utf-8")
    progress("\n" + format_report(rows))
    progress(f"\nVerdicts saved to {out}")
    return out
