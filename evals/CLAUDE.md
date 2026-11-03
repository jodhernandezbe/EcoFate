# evals/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `evals/`.

- Behavioral evaluation of the agent: run the production graph, prompt and tool descriptions
  with a real chat model and score what it did. Nothing in the project imports `evals`.
- The agent's model is built by `app.chat_model` from `[agent]`, the same model the program
  runs; never construct a chat model here. The judge model comes from `[evaluation]`.
- Module roles: `record.py` run record types, `cassette.py` record/replay of tool outputs,
  `runner.py` agent run + record extraction, `checks.py` deterministic checks,
  `scoring.py` Evidently adapter, judges and report, `scenarios.py` catalogue,
  `__main__.py` CLI (`record <scenario>`, `run`).
- Only `scoring.py` imports `evidently`, so a version change touches one file.
- `scenarios.csv` is the reviewed question catalogue (`question,category,type`; type is
  happy_path, varied_phrasing, edge_case, out_of_scope or breaking). A scripted `Scenario`
  in `scenarios.py` takes its query from a row, or adds the row in the same change; the CSV
  holds no expected answers. Its shape is checked by `tests/evals/test_scenarios_csv.py`.
- Cassettes in `evals/cassettes/` are recorded from live tools with
  `uv run python -m evals record <scenario>`; never write or edit tool outputs by hand.
  A scenario lists `extra_calls` for routes the agent may take instead of the one it took (the
  batch `assess_facilities` beside the per-facility tools); `record` makes them after the run,
  and `record-extra <scenario>` makes only them and adds them to the cassette.
  A replayed call with no recording fails closed and fails the scenario.
- Checks take expected values from the record's tool outputs, never from numbers written
  into the check. Judges answer one narrow PASS/FAIL criterion each.
- Judge model, key variable, live tools and paths come from `[evaluation]`; the agent model
  and step limit from `[agent]` in `config/settings.toml`.
- Unit tests of the harness use a scripted fake chat model and run in pre-commit; scenario
  runs are `@pytest.mark.eval` in `tests/evals/` (opt-in: `uv run pytest -m eval`).
