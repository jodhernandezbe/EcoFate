## Why

Labelling the 50 catalogue answers by hand (five-judge majority, `labels.json`) found 18 bad
responses and four recurring failure patterns: the CAS-identification rule breaking under
pressure, domain-flavoured off-topic requests being performed, values asked for that the
requested result does not use, and coverage/bookkeeping slips on large fan-outs. Checking
every future run by hand does not scale. An LLM judge that encodes those patterns, scored
against the human labels, turns the catalogue run into an automatic regression signal, and
its disagreements with the labels show where the judge prompt is still wrong.

## What Changes

- Add a judge for catalogue answers with structured output (`reasoning`, `label` good|bad,
  `failure` category or none), prompted with the failure patterns found during labelling and
  the rules of the agent's system prompt. The judge sees only the question and the answer,
  never the human label, the row's category or its type.
- Add a command, `uv run python -m evals judge <run-dir>`, that judges every row of a run's
  `catalogue.json`, writes `judged.json` next to it, and prints accuracy, precision and
  recall against `labels.json` (with `bad` as the positive class), the confusion matrix, and
  every disagreement with the human label, the judge's label and its reasoning.
- The judge model is the one configured in `[evaluation]` (`judge_provider`, `judge_model`,
  `judge_api_key_env_var`), built through the project's chat-model factory, with a new
  `judge_timeout_seconds` setting. A judge call that fails is recorded with its error and
  excluded from the metrics, never counted as a label.
- The judge prompt lives in `prompts/catalogue_judge.md` and is loaded through the prompt
  registry, so improving it is an edit to one Markdown file followed by a re-run.
- Unit tests with a fake judge model: no provider call.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `agent-evaluation`: adds a requirement for the catalogue judge (its inputs, structured
  verdict, prompt content, metrics against the human labels, disagreement report, failure
  handling).

## Impact

- `evals/catalogue/judge.py` (new), `evals/catalogue/metrics.py` (new), `evals/__main__.py`
  (new subcommand), `prompts/catalogue_judge.md` (new), `config/settings.toml` +
  `config/evaluation.py` (one key), root `CLAUDE.md` dependency line (`evals -> prompts`),
  `evals/CLAUDE.md`, README.
- `tests/evals/catalogue/test_judge.py`, `test_metrics.py`, `tests/config/`.
- No change to `agent/`, `tools/`, `api/` or `frontend/`. Running the judge costs tokens
  (50 calls to the judge model) and needs its API key; never in pre-commit or default pytest.
