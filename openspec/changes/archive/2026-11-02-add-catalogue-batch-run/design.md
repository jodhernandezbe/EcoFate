## Context

See proposal.md for motivation. What shapes the approach:

- Reference (`ai-buildcamp-2026/05-homework/evals/run_scenarios.py`): `csv.DictReader` over
  the CSV, `agent.run_sync(question)` per row, `time.time()` around it, a local
  `MODEL_PRICES` table, a list of dicts `{question, category, type, output, execution_time,
  tokens{input,output,total}, cost}` dumped to one JSON file, progress prints, total cost.
- This project already has the pieces the reference hand-rolls: `app.run.ask(question,
  model, keys) -> RunResult(answer, calls)` runs the agent exactly as `python -m app` does
  (stored keys with env fallback, step limit, Logfire session, `UsageRecorder` on every model
  call); `app.usage_meter.summarize_calls(calls, pricing) -> UsageSummary` gives tokens and a
  `Cost(usd, status, priced_on)` from `[ui.pricing]`, never guessing.
- `evals/__main__.py` is the evaluation CLI (`record`, `record-extra`, `run`);
  `evals/scoring.new_run_dir(settings)` makes `evals/reports/<timestamp>/`, gitignored.
- `evals/runner.py` keeps `_EXPECTED_ERRORS` (what a run may end with and still be a record).
- `evals/scenarios.py` is a module, so the package cannot be named `evals/scenarios/`
  (decided with the user: `evals/catalogue/`).
- Settings paths live in `config/settings.toml` with typed loaders (`config/evaluation.py`).
- User decisions (2026-11-02): folder `evals/catalogue/`; live run through `app.run.ask`,
  no subset flags; results in `evals/reports/<timestamp>/`.

## Goals / Non-Goals

**Goals:**
- One command that produces the reference's results file for this agent, with this
  project's metering, and that a unit test can drive without a provider.
- The CSV shape validation becomes product code (one reader), used by both the run and the
  test.

**Non-Goals:**
- Judging or labelling the answers (the reference's `judge.py`, `label_results.py`); a
  follow-up change.
- Replaying the catalogue from cassettes, parallel runs, retries, or resuming a partial run.
- Multi-turn rows (`same thing but for CAS 75-09-2` runs as a single turn; its answer will be
  a request for context, which is itself informative).
- Subset filters (`--type`, `--limit`): deliberately left out per the user's choice; add
  later if a run proves too costly.

## Decisions

1. **Package layout `evals/catalogue/`**: `__init__.py` (docstring only), `scenarios.csv`
   (moved with `git mv`), `rows.py` (reader), `run.py` (batch runner). Alternative: a flat
   `evals/catalogue.py` next to the CSV in `evals/` — rejected, the user wants the CSV and
   its code in one folder.
2. **Reader `rows.py`**: `CatalogueRow` frozen dataclass (`question`, `category`, `type`);
   `TYPES` frozenset; `read_rows(text: str) -> tuple[CatalogueRow, ...]` validates header,
   cell count, empty cells and type and raises `ValueError` naming the line;
   `load_catalogue(path) -> tuple[CatalogueRow, ...]` reads the file. The shape test calls
   `read_rows` for negatives and `load_catalogue(settings.catalogue)` for the real file.
   Validation moves out of the test so the run cannot start on a malformed file.
3. **Runner `run.py`** is injectable (dependency inversion): `run_catalogue(rows, ask:
   Callable[[str], RunResult], pricing, clock=time.perf_counter) -> tuple[RowResult, ...]`
   with `RowResult` a frozen dataclass (`question`, `category`, `type`, `output`,
   `execution_time`, `tokens: TokenCounts | None`, `cost: Cost | None`, `error: str | None`)
   and `to_json(results) -> str`. `tokens` and `cost` are `None` for a row whose run raised:
   `ask` builds its usage recorder internally and an exception propagates before the calls
   come back, so the usage is unknown and is not reported as zero (found at apply time). `TokenCounts` is a small frozen dataclass (`input_tokens`,
   `cached_input_tokens`, `output_tokens`, `total_tokens`, `calls`, `complete`) built from
   `UsageSummary`. A `progress: Callable[[str], None]` parameter receives the lines to print
   (default `print`), so the test asserts them without capturing stdout. The CLI wires the
   real `ask`: model built once with `program_model(get_agent_settings(), vaults.vault
   ("openai"))` and passed to `ask(question, model=model, keys=vaults)` so the key is read
   once, not fifty times.
4. **Expected errors**: rename `evals/runner._EXPECTED_ERRORS` to `EXPECTED_ERRORS` and reuse
   it in `run.py` (one source of truth for "what ends a run and is still a record"). `ask`
   raising anything else (including `RuntimeError` for a missing key, raised when the model
   is built before the loop) propagates and fails the command. Alternative: catch
   `Exception` per row — rejected (design principle: catch only expected exceptions).
5. **Cost and tokens from `app.usage_meter`**, not a price table: `summarize_calls
   (result.calls, get_ui_settings().pricing)`; `cost` is serialised as `{usd, status,
   priced_on}` so an unpriced model is visible, and `total_tokens = input + output` for
   parity with the reference.
6. **Output location**: `new_run_dir(get_evaluation_settings()) / settings.catalogue_results`
   (`catalogue.json`). JSON array, `indent=2`, `ensure_ascii=False`. Alternative: one JSON
   line per row streamed as rows finish (survives a crash mid-run) — rejected for parity
   with the reference; noted under risks.
7. **Settings**: `[evaluation].catalogue = "evals/catalogue/scenarios.csv"` (project path)
   and `[evaluation].catalogue_results = "catalogue.json"` (file name, non-empty, no path
   separators) added to `EvaluationSettings` with negative tests in `tests/config/`.
8. **CLI**: a `catalogue` subparser in `evals/__main__.py`, no arguments; `load_dotenv()`
   then `configure_telemetry(get_telemetry_settings())` as `app/__main__` does, so each row
   is a Logfire session when a token is set. The handler `_catalogue()` stays within the
   18-line rule by delegating to `run.py`'s `run_from_settings()`.
9. **Tests**: `tests/evals/catalogue/__init__.py`, `test_rows.py` (moved shape test plus
   `read_rows` negatives), `test_run.py` (fake `ask` returning a `RunResult` with known
   `CallUsage`; a fake that raises `GraphRecursionError` on one row; a fake clock; unpriced
   model; `to_json` round-trip). `tests/evals/test_scenarios_csv.py` is deleted.

## Risks / Trade-offs

- [A crash mid-run loses every row's result] → Expected errors are per-row; setup errors
  fail before row one. If unexpected provider errors prove common, switch to streaming JSON
  lines (decision 6 alternative).
- [50 live runs cost real money and hit EPA/Census/CompTox] → The command is opt-in, never in
  pre-commit or default pytest; the summary prints the total cost; subset flags are a
  one-line follow-up if needed.
- [`ask` builds the agent per call] → Cheap (graph wiring only); the model is built once.
- [Reference parity vs this project's metering] → Field names follow the reference where the
  meaning is the same (`output`, `execution_time`, `tokens.input_tokens`, `cost`); extra
  fields (`cached_input_tokens`, `calls`, `complete`, `cost.status`, `error`) are additive.
- [Moving the CSV changes the path recorded in the archived spec] → The delta spec updates
  the requirement text; `tests/evals/catalogue/test_rows.py` reads the path from settings.
