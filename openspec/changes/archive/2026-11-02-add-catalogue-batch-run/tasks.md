## 1. Settings

- [x] 1.1 Add `catalogue = "evals/catalogue/scenarios.csv"` and `catalogue_results = "catalogue.json"` to `[evaluation]` in `config/settings.toml`, with a comment on each.
- [x] 1.2 Add `catalogue: Path` (project path) and `catalogue_results: str` (non-empty, no path separator) to `EvaluationSettings` in `config/evaluation.py`; update its docstring.
- [x] 1.3 Add negative tests in `tests/config/` for a missing `catalogue`, an empty `catalogue_results` and one containing `/`.

## 2. Catalogue package

- [x] 2.1 `git mv evals/scenarios.csv evals/catalogue/scenarios.csv`; add `evals/catalogue/__init__.py` with a one-line docstring.
- [x] 2.2 Write `evals/catalogue/rows.py`: `TYPES`, `COLUMNS`, `CatalogueRow`, `read_rows(text)` raising `ValueError` naming the line for a wrong header, wrong cell count, empty cell or unknown type, and `load_catalogue(path)`.
- [x] 2.3 Rename `evals/runner._EXPECTED_ERRORS` to `EXPECTED_ERRORS` (update its two uses).
- [x] 2.4 Write `evals/catalogue/run.py`: `TokenCounts`, `RowResult`, `run_catalogue(rows, ask, pricing, clock, progress)`, `to_json(results)`, and `run_from_settings()` that builds the model once with `program_model`, wraps `app.run.ask`, writes `new_run_dir(...) / settings.catalogue_results`, and prints the final summary (rows, path, total cost or "could not be priced").

## 3. Command line

- [x] 3.1 Add the `catalogue` subcommand to `evals/__main__.py` (no arguments): `load_dotenv()`, `configure_telemetry(get_telemetry_settings())`, then `run_from_settings()`; update the module docstring's usage lines.

## 4. Tests

- [x] 4.1 Create `tests/evals/catalogue/__init__.py`; move `tests/evals/test_scenarios_csv.py` to `tests/evals/catalogue/test_rows.py`, reading the path from `get_evaluation_settings().catalogue` and the negatives through `read_rows` (`pytest.raises(ValueError, match=...)`).
- [x] 4.2 Write `tests/evals/catalogue/test_run.py` with a fake `ask`: every row answered (order, fields, positive time, `error` is None); one row raising `GraphRecursionError` is recorded and the rest continue; a non-expected exception propagates; unpriced model gives `cost.usd` None and status `unpriced`; progress lines per row; `to_json` round-trips.
- [x] 4.3 Add a test that `python -m evals catalogue` parses (argparse) without running the agent.

## 5. Documentation

- [x] 5.1 Update the `scenarios.csv` bullet in `evals/CLAUDE.md` to the new path, the reader and the `catalogue` command.
- [x] 5.2 Add `uv run python -m evals catalogue` to the README's evaluation section with a sentence on cost and keys.

## 6. Verification

- [x] 6.1 `uv run pytest tests/evals tests/config`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, function-length check, then `uv run pre-commit run --all-files`.
- [x] 6.2 Smoke-run the command once on the real catalogue only if the user asks (it costs tokens); otherwise confirm `uv run python -m evals catalogue --help` prints the subcommand.
