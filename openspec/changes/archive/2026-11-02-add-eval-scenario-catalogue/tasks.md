## 1. Catalogue

- [x] 1.1 Write `evals/scenarios.csv` verbatim from the fenced block in design.md ("The catalogue"): header `question,category,type`, 50 rows, fields with commas quoted.
- [x] 1.2 Verify by reading it back with `csv.DictReader`: 50 rows, 9 `breaking`, all five types present, no empty cell.

## 2. Shape test

- [x] 2.1 Add `tests/evals/test_scenarios_csv.py` (directory already has `__init__.py`): header, allowed types, >=50 rows, >=5 breaking, every type present, no empty cells.
- [x] 2.2 Add negative tests on in-memory CSV text: missing `type` column fails; unknown type value fails; empty question fails.

## 3. Documentation

- [x] 3.1 Add one bullet to `evals/CLAUDE.md`: `scenarios.csv` is the reviewed question catalogue; a scripted `Scenario` takes its query from a row (or adds the row).

## 4. Hook drift (added 2026-11-02: `add-trailing-comma` reformatted 249 files; user chose to keep it)

- [x] 4.1 Keep the hook's reformatting; split the 12 functions it pushed past 18 body lines into named helpers without changing behaviour: `config/stack.py:_parse_nei`, `tools/http.py:_attempt`, `config/pubchem.py:_limits`, `config/exposure.py:_age_bands`, `tools/assessment/facilities.py:_by_id`, `config/ui.py:_map`, `models/transport/screening.py:effective_release_height`, `tools/exposure/helpers/assessment.py:_assess`, `tools/emissions/helpers/industry/naics.py:_primary`, `models/transport/plume_rise.py:final_plume_rise`, `config/assessment.py:load_assessment_settings`, `config/frs_eis.py:load_frs_eis_settings`.

## 5. Verification

- [x] 5.1 Run `uv run pytest tests/evals`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, then `uv run pre-commit run --all-files`; audit any detect-secrets hit on the CSV rather than disabling the hook.
