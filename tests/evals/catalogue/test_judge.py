"""The judge: its prompt shows only the interaction, its verdict is consistent, and a failed
call is recorded without stopping the run."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evals.catalogue.judge import (
    FAILURES,
    PROMPT_NAME,
    Answer,
    JudgeVerdict,
    judge_one,
    judge_prompt,
    judge_rows,
)
from prompts.registry import load_prompt

ANSWERS = (
    Answer(0, "Assess CAS 71-43-2.", "Screening assessment ... HQ 0.2 (TRI, NEI, Census)."),
    Answer(1, "Run an assessment for formaldehyde air releases.", "Please give me the CAS number."),
)


def _verdict(label: str, failure: str | None = None) -> JudgeVerdict:
    """Build through validation from plain strings, as the model's JSON arrives."""
    fields = {"reasoning": "checked every criterion", "label": label, "failure": failure}
    return JudgeVerdict.model_validate(fields)


def test_prompt_holds_question_and_answer_only() -> None:
    text = judge_prompt("Assess CAS 71-43-2.", "HQ 0.2 for the one facility")
    assert "Assess CAS 71-43-2." in text and "HQ 0.2 for the one facility" in text
    for leak in ("label", "category", "type", "votes", "reason"):
        assert leak not in text.lower()


def test_prompt_file_loads_and_names_every_failure_category() -> None:
    criteria = load_prompt(PROMPT_NAME)
    assert all(tag in criteria for tag in ("<role>", "<instructions>", "<output_format>"))
    assert all(failure in criteria for failure in FAILURES)


def test_good_verdict_rejects_a_failure_category() -> None:
    with pytest.raises(ValidationError, match="no failure category"):
        _verdict("good", "rule-break")


def test_bad_verdict_without_category_becomes_other() -> None:
    assert _verdict("bad").failure == "other"


def test_label_must_be_good_or_bad() -> None:
    with pytest.raises(ValidationError):
        _verdict("fine")


def test_judge_rows_keeps_order_and_records_one_failed_call() -> None:
    def scripted(question: str, answer: str) -> JudgeVerdict:
        if "formaldehyde" in question:
            raise ValueError("no parseable verdict")
        return _verdict("bad", "incomplete")

    lines: list[str] = []
    first, second = judge_rows(ANSWERS, scripted, progress=lines.append)
    assert (first.index, first.label, first.failure, first.error) == (0, "bad", "incomplete", None)
    assert first.reasoning == "checked every criterion"
    assert (second.index, second.label, second.failure) == (1, None, None)
    assert second.error == "ValueError: no parseable verdict"
    assert lines[0] == f"[1/2] {ANSWERS[0].question}" and lines[1] == "  bad (incomplete)"
    assert lines[3].startswith("  error: ValueError")


def test_unexpected_error_propagates() -> None:
    def broken(question: str, answer: str) -> JudgeVerdict:
        raise KeyError(question)

    with pytest.raises(KeyError):
        judge_one(ANSWERS[0], broken)
