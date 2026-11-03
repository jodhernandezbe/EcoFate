## Why

`evals/scenarios.csv` holds 50 reviewed questions but nothing runs them: the existing
harness only replays scripted scenarios with cassettes, and none of the 50 has one. The
reference `run_scenarios.py` (ai-buildcamp-2026, 05-homework) shows the shape wanted: read
the CSV, send every question to the live agent, and save each answer with its execution
time, token counts and cost to one JSON file, so the answers can be read, labelled and
judged afterwards.

## What Changes

- Move the catalogue into its own package, `evals/catalogue/`: the CSV (`scenarios.csv`),
  the row reader with the shape validation that today lives only in a test, and the batch
  runner. `evals/scenarios.py` (scripted scenarios with cassettes) is untouched.
- Add a command, `uv run python -m evals catalogue`, that runs every row through the live
  agent by the same path as `python -m app` (configured model, stored keys, step limit,
  telemetry, metered usage), prints progress per row, and writes
  `evals/reports/<timestamp>/catalogue.json` with, per row: question, category, type, the
  answer, execution time, token counts, estimated cost, and the error if the row did not
  finish. A row that fails for an expected reason is recorded, not fatal; a missing key
  stops the command before any row runs.
- Cost and tokens come from `app.usage_meter` and `[ui.pricing]`, never from a price table in
  the script; a model with no configured price gives `cost: null` with its status, not a
  guessed number.
- Catalogue and result file names come from `[evaluation]` in `config/settings.toml`.
- Move the shape test to `tests/evals/catalogue/` and add a unit test of the runner with a
  fake `ask` (no provider call).
- Update `evals/CLAUDE.md` and the README's evaluation commands.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `agent-evaluation`: the catalogue requirement's file path moves to
  `evals/catalogue/scenarios.csv`; a new requirement defines the batch run over the catalogue
  (inputs, result record, error handling, where results go).

## Impact

- `evals/catalogue/` (new package: `__init__.py`, `scenarios.csv`, `rows.py`, `run.py`),
  `evals/__main__.py` (new subcommand), `evals/runner.py` (expose the expected-error tuple),
  `config/evaluation.py` + `config/settings.toml` (two keys), `evals/CLAUDE.md`, `README.md`.
- `tests/evals/catalogue/` (new; `test_scenarios_csv.py` moves there), `tests/config/`.
- No change to `agent/`, `tools/`, `api/` or `frontend/`. Dependency direction stays
  `evals -> app/agent/config`.
- Running the command costs tokens and needs the OpenAI key (and Census/CompTox keys for
  full answers); it is never part of pre-commit or the default pytest run.
