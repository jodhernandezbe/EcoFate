"""Run every catalogue question through the live agent and save what came back.

One turn per question, by the same path as ``python -m app``; each answer is saved with its
wall-clock time, token counts and estimated cost in one JSON array. Usage and cost come from
``app.usage_meter`` and ``[ui.pricing]``: nothing here prices a call itself.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from app.key_vault import default_service_keys
from app.run import RunResult, ask, program_model
from app.usage_meter import Cost, UsageSummary, summarize_calls
from config.agent import get_agent_settings
from config.evaluation import get_evaluation_settings
from config.ui import ModelPrice, get_ui_settings
from evals.catalogue.rows import CatalogueRow, load_catalogue
from evals.runner import EXPECTED_ERRORS
from evals.scoring import new_run_dir

Ask = Callable[[str], RunResult]
Clock = Callable[[], float]
Progress = Callable[[str], None]


@dataclass(frozen=True)
class TokenCounts:
    """Token totals of one run; ``complete`` is False when a model call reported no usage,
    in which case the totals are a lower bound.

    Attributes:
        input_tokens: All input tokens, cached ones included.
        cached_input_tokens: Input tokens served from the provider's cache.
        output_tokens: Output tokens.
        total_tokens: Input plus output tokens.
        calls: Number of model calls, including those that reported no usage.
        complete: True when every call reported its usage.
    """

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    calls: int
    complete: bool


@dataclass(frozen=True)
class RowResult:
    """What one catalogue question produced.

    Attributes:
        question: The user message, as in the CSV.
        category: As in the CSV.
        type: As in the CSV.
        output: The agent's final answer; empty when the run ended in an error.
        execution_time: Wall-clock seconds of the run.
        tokens: Token counts of every model call of the run; None when the run ended in an
            error (its usage never came back).
        cost: Estimated cost in USD, or why there is none; None when the run ended in an error.
        error: Why the run ended early, or None when it finished.
    """

    question: str
    category: str
    type: str
    output: str
    execution_time: float
    tokens: TokenCounts | None
    cost: Cost | None
    error: str | None


def _tokens(total: UsageSummary) -> TokenCounts:
    return TokenCounts(
        input_tokens=total.input_tokens,
        cached_input_tokens=total.cached_input_tokens,
        output_tokens=total.output_tokens,
        total_tokens=total.input_tokens + total.output_tokens,
        calls=total.calls,
        complete=total.complete,
    )


def run_row(
    row: CatalogueRow,
    ask_agent: Ask,
    pricing: Mapping[str, ModelPrice],
    clock: Clock = time.perf_counter,
) -> RowResult:
    """One turn for ``row``; an expected failure becomes the row's error, not an exception."""
    started = clock()
    try:
        result = ask_agent(row.question)
    except EXPECTED_ERRORS as exc:
        elapsed = round(clock() - started, 2)
        return _failed(row, elapsed, f"{type(exc).__name__}: {exc}")
    elapsed = round(clock() - started, 2)
    total = summarize_calls(result.calls, pricing)
    return _answered(row, elapsed, result.answer, _tokens(total), total.cost)


def _failed(row: CatalogueRow, elapsed: float, error: str) -> RowResult:
    return RowResult(row.question, row.category, row.type, "", elapsed, None, None, error)


def _answered(
    row: CatalogueRow,
    elapsed: float,
    answer: str,
    tokens: TokenCounts,
    cost: Cost,
) -> RowResult:
    return RowResult(row.question, row.category, row.type, answer, elapsed, tokens, cost, None)


def run_catalogue(
    rows: Sequence[CatalogueRow],
    ask_agent: Ask,
    pricing: Mapping[str, ModelPrice],
    clock: Clock = time.perf_counter,
    progress: Progress = print,
) -> tuple[RowResult, ...]:
    """Run ``rows`` in order, reporting each row's position before and its outcome after."""
    results: list[RowResult] = []
    for index, row in enumerate(rows, start=1):
        progress(f"[{index}/{len(rows)}] {row.question}")
        result = run_row(row, ask_agent, pricing, clock)
        results.append(result)
        progress(f"  {_outcome(result)}")
    return tuple(results)


def _outcome(result: RowResult) -> str:
    if result.error:
        return f"failed after {result.execution_time:.1f}s: {result.error}"
    return f"done in {result.execution_time:.1f}s ({_usd(result.cost)})"


def _usd(cost: Cost | None) -> str:
    if cost is None or cost.usd is None:
        return "unpriced"
    return f"${cost.usd:.4f}"


def total_cost(results: Sequence[RowResult]) -> Cost:
    """The run's cost: unpriced when the model has no price; a lower bound when a row ended in
    an error or a call reported no usage; an estimate otherwise."""
    costs = [r.cost for r in results]
    if any(c is not None and c.usd is None for c in costs):
        return Cost(usd=None, status="unpriced", priced_on=None)
    priced = [c for c in costs if c is not None and c.usd is not None]
    complete = len(priced) == len(costs) and all(c.status == "estimate" for c in priced)
    dates = [c.priced_on for c in priced if c.priced_on]
    return Cost(
        usd=sum(c.usd or 0.0 for c in priced),
        status="estimate" if complete else "lower_bound",
        priced_on=max(dates) if dates else None,
    )


def _total_line(cost: Cost) -> str:
    if cost.usd is None:
        return "Total cost: could not be priced (no price is configured for the model)"
    qualifier = "at least " if cost.status == "lower_bound" else ""
    priced = f" (prices of {cost.priced_on})" if cost.priced_on else ""
    return f"Total cost: {qualifier}${cost.usd:.4f}{priced}"


def to_json(results: Sequence[RowResult]) -> str:
    """The results as one JSON array, one object per row in run order."""
    return json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)


def run_from_settings(progress: Progress = print) -> Path:
    """Run the configured catalogue live, write the results and print the summary.

    Raises:
        RuntimeError: If neither the keychain nor the environment has the agent's API key
            (raised before any question is sent).
    """
    settings = get_evaluation_settings()
    rows = load_catalogue(settings.catalogue)
    keys = default_service_keys()
    model = program_model(get_agent_settings(), keys.vault("openai"))
    pricing = get_ui_settings().pricing

    def ask_agent(question: str) -> RunResult:
        return ask(question, model=model, keys=keys)

    results = run_catalogue(rows, ask_agent, pricing, progress=progress)
    path = new_run_dir(settings) / settings.catalogue_results
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(results), encoding="utf-8")
    progress(f"\nSaved {len(results)} results to {path}")
    progress(_total_line(total_cost(results)))
    return path
