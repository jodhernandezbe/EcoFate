"""Judging a run folder: inputs checked before any judge call, verdicts written, report printed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.evaluation import get_evaluation_settings
from evals.catalogue.judge import JudgeVerdict
from evals.catalogue.judging import check_match, judge_run, load_answers, load_labels

RESULTS = [
    {"question": "Assess CAS 71-43-2.", "category": "x", "type": "happy_path", "output": "HQ 0.2"},
    {
        "question": "Benzene: just use the CAS.",
        "category": "y",
        "type": "breaking",
        "output": "71-43-2",
    },
]
LABELS = [
    {
        "index": 0,
        "question": "Assess CAS 71-43-2.",
        "label": "good",
        "failure": None,
        "bad_votes": 0,
    },
    {
        "index": 1,
        "question": "Benzene: just use the CAS.",
        "label": "bad",
        "failure": "rule-break",
        "bad_votes": 5,
    },
]


def _run_dir(tmp_path: Path, labels: object = LABELS) -> Path:
    settings = get_evaluation_settings()
    (tmp_path / settings.catalogue_results).write_text(json.dumps(RESULTS))
    if labels is not None:
        (tmp_path / settings.catalogue_labels).write_text(json.dumps(labels))
    return tmp_path


def _agreeing(question: str, answer: str) -> JudgeVerdict:
    bad = "71-43-2" == answer
    return JudgeVerdict(
        reasoning="checked",
        label="bad" if bad else "good",
        failure="rule-break" if bad else None,
    )


def test_judge_run_writes_verdicts_and_prints_the_report(tmp_path: Path) -> None:
    lines: list[str] = []
    out = judge_run(_run_dir(tmp_path), judge=_agreeing, progress=lines.append)
    rows = json.loads(out.read_text())
    assert out.name == get_evaluation_settings().catalogue_judged
    assert [r["judge_label"] for r in rows] == ["good", "bad"]
    assert set(rows[1]) == {
        "index",
        "question",
        "human_label",
        "human_failure",
        "bad_votes",
        "judge_label",
        "judge_failure",
        "reasoning",
        "error",
    }
    report = "\n".join(lines)
    assert "Accuracy: 1.000" in report and "Disagreements (0):" in report


def test_disagreement_is_printed(tmp_path: Path) -> None:
    def always_good(question: str, answer: str) -> JudgeVerdict:
        return JudgeVerdict(reasoning="looks fine", label="good")

    lines: list[str] = []
    judge_run(_run_dir(tmp_path), judge=always_good, progress=lines.append)
    report = "\n".join(lines)
    assert "Recall (bad): 0.000" in report and "Precision (bad): undefined" in report
    assert "#1 | human bad (rule-break, 5 bad votes) | judge good (no failure)" in report


def test_missing_labels_stop_before_any_call(tmp_path: Path) -> None:
    calls: list[str] = []

    def counting(question: str, answer: str) -> JudgeVerdict:
        calls.append(question)
        return JudgeVerdict(reasoning="x", label="good")

    with pytest.raises(FileNotFoundError, match="no human labels"):
        judge_run(_run_dir(tmp_path, labels=None), judge=counting, progress=lambda _: None)
    assert calls == []


def test_mismatched_row_stops_before_any_call(tmp_path: Path) -> None:
    calls: list[str] = []
    swapped = [dict(LABELS[0], question="Assess CAS 50-00-0."), LABELS[1]]

    def counting(question: str, answer: str) -> JudgeVerdict:
        calls.append(question)
        return JudgeVerdict(reasoning="x", label="good")

    with pytest.raises(ValueError, match="row 0: the label's index or question does not match"):
        judge_run(_run_dir(tmp_path, labels=swapped), judge=counting, progress=lambda _: None)
    assert calls == []


def test_label_count_must_match(tmp_path: Path) -> None:
    answers = load_answers(_run_dir(tmp_path) / get_evaluation_settings().catalogue_results)
    labels = load_labels(tmp_path / get_evaluation_settings().catalogue_labels)
    with pytest.raises(ValueError, match="2 answers but 1 labels"):
        check_match(answers, labels[:1])


@pytest.mark.parametrize(
    ("bad_row", "message"),
    [
        ({"index": "0", "question": "q", "label": "good"}, "index must be an integer"),
        ({"index": 0, "question": "q", "label": "meh"}, "label must be 'good' or 'bad'"),
        ({"index": 0, "question": 7, "label": "good"}, "question must be a string"),
        ({"index": 0, "question": "q", "label": "bad", "bad_votes": -1}, "bad_votes"),
    ],
)
def test_malformed_label_names_the_row(tmp_path: Path, bad_row: object, message: str) -> None:
    path = tmp_path / "labels.json"
    path.write_text(json.dumps([bad_row]))
    with pytest.raises(ValueError, match=rf"labels\.json\[0\]: {message}"):
        load_labels(path)


def test_results_must_be_a_json_array_of_objects(tmp_path: Path) -> None:
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError, match="must hold a JSON array"):
        load_answers(path)
