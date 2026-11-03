"""Agreement between the LLM judge and the human labels: counts, metrics and disagreements.

Pure: no I/O, no model. ``bad`` is the positive class, so precision is "of the rows the judge
called bad, how many the humans called bad" and recall is "of the human-bad rows, how many the
judge caught". Rows the judge could not label are excluded from the metrics and counted apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

BAD = "bad"
GOOD = "good"


@dataclass(frozen=True)
class Labelled:
    """One row with its human label and the judge's verdict.

    Attributes:
        index: Position of the row in the run's results.
        question: The user message.
        human_label: 'good' or 'bad' from the human labels.
        human_failure: The humans' failure category, or None.
        bad_votes: How many human judges voted bad, when known.
        judge_label: The LLM judge's label, or None when its call failed.
        judge_failure: The LLM judge's failure category, or None.
        reasoning: The LLM judge's reasoning.
        error: Why the judge call failed, or None.
    """

    index: int
    question: str
    human_label: str
    human_failure: str | None
    bad_votes: int | None
    judge_label: str | None
    judge_failure: str | None
    reasoning: str
    error: str | None


@dataclass(frozen=True)
class Confusion:
    """Counts with ``bad`` as the positive class, over the rows the judge labelled."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def judged(self) -> int:
        """Rows that received a judge label."""
        return self.tp + self.fp + self.fn + self.tn


def confusion(rows: Sequence[Labelled]) -> Confusion:
    """Count the judged rows into the four cells; unjudged rows are left out."""
    judged = [r for r in rows if r.judge_label is not None]
    return Confusion(
        tp=sum(r.human_label == BAD and r.judge_label == BAD for r in judged),
        fp=sum(r.human_label == GOOD and r.judge_label == BAD for r in judged),
        fn=sum(r.human_label == BAD and r.judge_label == GOOD for r in judged),
        tn=sum(r.human_label == GOOD and r.judge_label == GOOD for r in judged),
    )


def accuracy(c: Confusion) -> float | None:
    """Share of judged rows where the labels agree; None when nothing was judged."""
    return None if c.judged == 0 else (c.tp + c.tn) / c.judged


def precision(c: Confusion) -> float | None:
    """Of the rows the judge called bad, the share the humans called bad; None if none."""
    return None if c.tp + c.fp == 0 else c.tp / (c.tp + c.fp)


def recall(c: Confusion) -> float | None:
    """Of the human-bad rows, the share the judge called bad; None if there are none."""
    return None if c.tp + c.fn == 0 else c.tp / (c.tp + c.fn)


def disagreements(rows: Sequence[Labelled]) -> tuple[Labelled, ...]:
    """The judged rows whose judge label differs from the human label, in order."""
    return tuple(r for r in rows if r.judge_label is not None and r.judge_label != r.human_label)


def _metric(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"


def _votes(row: Labelled) -> str:
    return f", {row.bad_votes} bad votes" if row.bad_votes is not None else ""


def _disagreement(row: Labelled) -> str:
    human = f"{row.human_label} ({row.human_failure or 'no failure'}{_votes(row)})"
    judge = f"{row.judge_label} ({row.judge_failure or 'no failure'})"
    return "\n".join(
        [
            f"  #{row.index} | human {human} | judge {judge}",
            f"      Q: {row.question}",
            f"      reasoning: {row.reasoning}",
        ],
    )


def format_report(rows: Sequence[Labelled]) -> str:
    """The agreement report: counts, the three metrics, the confusion matrix, disagreements."""
    c = confusion(rows)
    errors = len(rows) - c.judged
    differing = disagreements(rows)
    lines = [
        f"Judged {c.judged} of {len(rows)} rows ({errors} judge errors)",
        f"Accuracy: {_metric(accuracy(c))}   Precision (bad): {_metric(precision(c))}   "
        f"Recall (bad): {_metric(recall(c))}",
        "Confusion (human x judge)   judge good   judge bad",
        f"  human good                {c.tn:^10}   {c.fp:^9}",
        f"  human bad                 {c.fn:^10}   {c.tp:^9}",
        f"Disagreements ({len(differing)}):",
        *(_disagreement(r) for r in differing),
    ]
    return "\n".join(lines)
