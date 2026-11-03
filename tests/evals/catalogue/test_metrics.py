"""Agreement metrics with ``bad`` as the positive class, undefined when there is no denominator."""

from __future__ import annotations

import pytest

from evals.catalogue.metrics import (
    Confusion,
    Labelled,
    accuracy,
    confusion,
    disagreements,
    format_report,
    precision,
    recall,
)


def _row(index: int, human: str, judge: str | None, failure: str | None = None) -> Labelled:
    return Labelled(
        index=index,
        question=f"q{index}",
        human_label=human,
        human_failure="rule-break" if human == "bad" else None,
        bad_votes=5 if human == "bad" else 0,
        judge_label=judge,
        judge_failure=failure if judge == "bad" else None,
        reasoning="because" if judge else "",
        error=None if judge else "APIError: timeout",
    )


MIXED = (
    _row(0, "bad", "bad", "rule-break"),
    _row(1, "bad", "good"),
    _row(2, "good", "bad", "incomplete"),
    _row(3, "good", "good"),
    _row(4, "good", "good"),
    _row(5, "bad", None),
)


def test_confusion_counts_judged_rows_only() -> None:
    assert confusion(MIXED) == Confusion(tp=1, fp=1, fn=1, tn=2)
    assert confusion(MIXED).judged == 5


def test_metrics_on_the_mixed_case() -> None:
    c = confusion(MIXED)
    assert accuracy(c) == pytest.approx(3 / 5)
    assert precision(c) == pytest.approx(1 / 2)
    assert recall(c) == pytest.approx(1 / 2)


def test_all_good_predictions_leave_precision_undefined() -> None:
    c = confusion((_row(0, "bad", "good"), _row(1, "good", "good")))
    assert precision(c) is None
    assert recall(c) == 0.0
    assert accuracy(c) == pytest.approx(1 / 2)


def test_no_human_bad_rows_leave_recall_undefined() -> None:
    c = confusion((_row(0, "good", "good"), _row(1, "good", "bad", "other")))
    assert recall(c) is None
    assert precision(c) == 0.0


def test_nothing_judged_leaves_everything_undefined() -> None:
    c = confusion((_row(0, "bad", None),))
    assert (accuracy(c), precision(c), recall(c)) == (None, None, None)


def test_disagreements_exclude_unjudged_rows() -> None:
    assert [r.index for r in disagreements(MIXED)] == [1, 2]


def test_report_names_counts_metrics_and_each_disagreement() -> None:
    report = format_report(MIXED)
    assert "Judged 5 of 6 rows (1 judge errors)" in report
    assert "Accuracy: 0.600" in report and "Precision (bad): 0.500" in report
    assert "Disagreements (2):" in report
    assert "#1 | human bad (rule-break, 5 bad votes) | judge good (no failure)" in report
    assert "#2 | human good (no failure, 0 bad votes) | judge bad (incomplete)" in report
    assert "reasoning: because" in report


def test_report_says_undefined() -> None:
    assert "Precision (bad): undefined" in format_report((_row(0, "bad", "good"),))
