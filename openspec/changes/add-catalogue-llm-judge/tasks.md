## 1. Settings and prompt

- [x] 1.1 Add `judge_timeout_seconds` to `[evaluation]` in `config/settings.toml` (with a comment) and to `EvaluationSettings` in `config/evaluation.py` (positive number); add a negative test in `tests/config/test_evaluation_settings.py` and update `tests/evals/test_scoring.py`'s hand-built settings.
- [x] 1.2 Write `prompts/catalogue_judge.md` (`<role>`, `<context>`, `<instructions>` with GOOD criteria and BAD criteria per failure category carrying the labelling patterns, `<output_format>`); add `evals -> prompts` to the dependency line in the root `CLAUDE.md` (stay within the line budget checked by `tests/test_claude_md.py`).

## 2. Judge

- [x] 2.1 Write `evals/catalogue/judge.py`: `FAILURES`, `JudgeVerdict` (reasoning, label, failure; validator), `JudgeResult` (index, question, label, failure, reasoning, error), `judge_prompt(question, answer)`, `Judge` type, `build_judge(settings)` via `build_named_chat_model` + `with_structured_output(..., include_raw=True)`, and `judge_rows(rows, judge, progress)` that records a failed call as an error and continues.
- [x] 2.2 Write `evals/catalogue/metrics.py` (pure): `Confusion`, `confusion(pairs)`, `accuracy`, `precision`, `recall` returning `None` when undefined, `disagreements(...)`, `format_report(...)` (counts, metrics as `undefined` when None, confusion matrix, one block per disagreement with bad-vote count, both failure categories and the reasoning).
- [x] 2.3 Write `evals/catalogue/judging.py`: `load_labels(path)` (fail-closed shape check), `check_match(results, labels)` (same length, index and question row for row), `judge_run(run_dir, judge=None, progress=print) -> Path` that writes `judged.json` and prints the report.

## 3. Command line

- [x] 3.1 Add the `judge <run_dir>` subcommand to `evals/__main__.py` (`load_dotenv()`, then `judge_run`); update the module docstring.

## 4. Tests

- [x] 4.1 `tests/evals/catalogue/test_judge.py`: prompt contains question and answer and none of label/category/type/reasons; prompt file loads through the registry and names every failure category; `JudgeVerdict` validator cases; `judge_rows` with a scripted fake judge where one row raises (recorded with error, others judged, order kept).
- [x] 4.2 `tests/evals/catalogue/test_metrics.py`: hand-built pairs for a mixed case, all-good predictions (precision undefined, recall 0), all-bad human labels, rows with errors excluded; `format_report` names `undefined`.
- [x] 4.3 `tests/evals/catalogue/test_judging.py`: tmp run folder with two-row `catalogue.json` + `labels.json` and an injected fake judge writes `judged.json` with the expected fields and prints the disagreement; missing `labels.json` and a mismatched row both fail before any judge call.
- [x] 4.4 Extend `tests/evals/test_main.py` with the `judge` subcommand (monkeypatched `judge_run`).

## 5. Documentation

- [x] 5.1 Add the judge to the `catalogue/` bullet in `evals/CLAUDE.md` and the `judge` command (plus a sentence on the baseline workflow: run, label, judge, read disagreements, edit the prompt, re-run) to the README's evaluation section.

## 6. Verification

- [x] 6.1 `uv run pytest tests/evals tests/config tests/test_claude_md.py`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, function-length check, `uv run pre-commit run --all-files` (twice, to confirm stability under the trailing-comma hook).
- [x] 6.2 Run `uv run python -m evals judge evals/reports/20261102-195041` once (costs tokens; the user asked for it) and report the baseline accuracy, precision, recall and the disagreements.
