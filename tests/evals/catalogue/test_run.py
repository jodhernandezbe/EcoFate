"""The batch runner with a fake agent: no provider, no network."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from itertools import count

import pytest
from langgraph.errors import GraphRecursionError

from app.run import RunResult
from app.usage_meter import CallUsage
from config.ui import ModelPrice
from evals.catalogue.rows import CatalogueRow
from evals.catalogue.run import RowResult, run_catalogue, run_row, to_json, total_cost

MODEL = "test-model"
PRICING = {
    MODEL: ModelPrice(
        input_usd_per_mtok=1.0,
        cached_input_usd_per_mtok=0.5,
        output_usd_per_mtok=2.0,
        priced_on=date(2026, 1, 1),
        source_url="https://example.test/prices",
    ),
}
ROWS = (
    CatalogueRow("Assess CAS 71-43-2.", "full-assessment-cas", "happy_path"),
    CatalogueRow("Assess CAS 95-57-8.", "tri-category-member", "edge_case"),
)


def _call(input_tokens: int = 1000, output_tokens: int = 500, cached: int = 0) -> CallUsage:
    return CallUsage(MODEL, input_tokens, cached, output_tokens)


def _answers(question: str) -> RunResult:
    return RunResult(f"answer to {question}", (_call(), _call(cached=200)))


def _ticking() -> Callable[[], float]:
    """A clock that advances 1.5 s per reading."""
    ticks = count(0.0, 1.5)
    return lambda: next(ticks)


def test_every_row_answered_in_order() -> None:
    clock = _ticking()
    results = run_catalogue(ROWS, _answers, PRICING, clock=clock, progress=lambda _: None)
    assert [r.question for r in results] == [r.question for r in ROWS]
    assert [(r.category, r.type) for r in results] == [(r.category, r.type) for r in ROWS]
    assert all(r.output == f"answer to {r.question}" for r in results)
    assert all(r.execution_time == 1.5 for r in results)
    assert all(r.error is None for r in results)


def test_tokens_and_cost_come_from_the_meter() -> None:
    result = run_row(ROWS[0], _answers, PRICING, clock=count(0.0).__next__)
    assert result.tokens is not None and result.cost is not None
    assert (result.tokens.input_tokens, result.tokens.output_tokens) == (2000, 1000)
    assert result.tokens.cached_input_tokens == 200
    assert result.tokens.total_tokens == 3000
    assert (result.tokens.calls, result.tokens.complete) == (2, True)
    # 1800 uncached in * 1.0 + 200 cached * 0.5 + 1000 out * 2.0, per million
    assert result.cost.usd == pytest.approx((1800 * 1.0 + 200 * 0.5 + 1000 * 2.0) / 1e6)
    assert (result.cost.status, result.cost.priced_on) == ("estimate", "2026-01-01")


def test_expected_error_is_recorded_and_the_run_goes_on() -> None:
    def flaky(question: str) -> RunResult:
        if question == ROWS[0].question:
            raise GraphRecursionError("step limit")
        return _answers(question)

    results = run_catalogue(ROWS, flaky, PRICING, progress=lambda _: None)
    first, second = results
    assert first.output == "" and first.tokens is None and first.cost is None
    assert first.error == "GraphRecursionError: step limit"
    assert second.error is None and second.output.startswith("answer to")


def test_unexpected_error_propagates() -> None:
    def broken(question: str) -> RunResult:
        raise KeyError(question)

    with pytest.raises(KeyError):
        run_catalogue(ROWS[:1], broken, PRICING, progress=lambda _: None)


def test_unpriced_model_has_no_figure() -> None:
    result = run_row(ROWS[0], _answers, {}, clock=count(0.0).__next__)
    assert result.cost is not None
    assert (result.cost.usd, result.cost.status) == (None, "unpriced")
    assert result.tokens is not None and result.tokens.total_tokens == 3000


def test_progress_reports_each_row_before_and_after() -> None:
    lines: list[str] = []
    clock = _ticking()
    run_catalogue(ROWS, _answers, PRICING, clock=clock, progress=lines.append)
    assert lines[0] == f"[1/2] {ROWS[0].question}"
    assert lines[1].startswith("  done in 1.5s ($")
    assert lines[2] == f"[2/2] {ROWS[1].question}"


def test_progress_names_a_failed_row() -> None:
    lines: list[str] = []

    def failing(question: str) -> RunResult:
        raise GraphRecursionError("step limit")

    run_catalogue(ROWS[:1], failing, PRICING, progress=lines.append)
    assert lines[1].startswith("  failed after ") and lines[1].endswith("step limit")


def _result(cost_usd: float | None, status: str, error: str | None = None) -> RowResult:
    from app.usage_meter import Cost  # noqa: PLC0415  # local to keep the helper self-contained

    cost = None if error else Cost(cost_usd, status, "2026-01-01" if cost_usd else None)
    return RowResult("q", "c", "happy_path", "" if error else "a", 1.0, None, cost, error)


def test_total_cost_sums_estimates() -> None:
    total = total_cost([_result(0.01, "estimate"), _result(0.02, "estimate")])
    assert (total.usd, total.status, total.priced_on) == (
        pytest.approx(0.03),
        "estimate",
        "2026-01-01",
    )


def test_total_cost_is_a_lower_bound_when_a_row_failed() -> None:
    total = total_cost([_result(0.01, "estimate"), _result(None, "", error="boom")])
    assert (total.usd, total.status) == (pytest.approx(0.01), "lower_bound")


def test_total_cost_is_unpriced_when_the_model_has_no_price() -> None:
    total = total_cost([_result(None, "unpriced"), _result(None, "unpriced")])
    assert (total.usd, total.status) == (None, "unpriced")


def test_to_json_round_trips_every_field() -> None:
    results = run_catalogue(ROWS, _answers, PRICING, progress=lambda _: None)
    data = json.loads(to_json(results))
    assert [d["question"] for d in data] == [r.question for r in ROWS]
    assert set(data[0]) == {
        "question",
        "category",
        "type",
        "output",
        "execution_time",
        "tokens",
        "cost",
        "error",
    }
    assert data[0]["tokens"]["total_tokens"] == 3000
    assert data[0]["cost"]["status"] == "estimate"
    assert data[0]["error"] is None
