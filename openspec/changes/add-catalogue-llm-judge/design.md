## Context

See proposal.md for motivation. What shapes the approach:

- Reference (`ai-engineering-buildcamp-code/documentation-agent/evals/manual`): `judge.py`
  defines a pydantic `JudgeEvaluation(reasoning, label)` and a strict instruction block
  ("be extremely strict", step-by-step before the label); `run_judge.py` judges each row,
  computes accuracy/precision/recall with `bad` as the positive class, prints a confusion
  matrix and the disagreements (question, human label + comment, judge label + reasoning).
  It falls back to `label="bad"` on a judge error; this project fails closed instead.
- Project pieces to reuse: `app.chat_model.build_named_chat_model(provider, model,
  api_key_env_var, timeout_seconds)` (the one provider import); structured output via
  `model.with_structured_output(PydanticModel, include_raw=True)` as in
  `agent/completion.py`; `[evaluation]` already names the judge provider, model and key
  variable (used by the Evidently judges in `evals/scoring.py`); prompts are Markdown files
  under `prompts/` loaded with `prompts.registry.load_prompt`, structured with XML tags.
- Inputs: `evals/reports/<ts>/catalogue.json` (50 rows: question, category, type, output…)
  and `labels.json` from the five-judge vote (index, question, category, type, label,
  failure, failure_votes, reasons). Both exist for run `20261102-195041`.
- Failure patterns found (18 bad of 50): rule-break 9 (CAS from memory, after a "SYSTEM
  OVERRIDE", as an "example"; asking for an IUR when only an HQ was requested or for vapour
  pressure that no equation uses; ending with "shall I proceed?"), wrong-scope 3 (TRI
  scraper code, cease-and-desist letter, EPA politics), incomplete 3 (10 of 21 facilities as
  "full results", a Texas request narrowed to one facility, a "not reported vs zero"
  question answered only with a CAS request), incorrect 2 (29 vs 43 screened-out counts,
  four facilities named but three tabulated, 2.1e-4 cancer risk called below concern),
  hallucination 1 (schools and children claimed near facilities).
- Human-judge disagreement was on long happy-path assessments (completeness threshold),
  never on rule-break or scope rows.

## Goals / Non-Goals

**Goals:**
- A judge whose verdict is explainable (reasoning first), reproducible (temperature 0 where
  the model allows), and scored against the human labels with the three metrics plus a
  disagreement list that points at the prompt sentence to improve.
- Prompt iteration without code changes: edit `prompts/catalogue_judge.md`, re-run.

**Non-Goals:**
- Replacing the Evidently PASS/FAIL judges of the scripted scenarios.
- Giving the judge tool outputs (the catalogue run does not record them); it judges the
  answer's rule adherence and internal consistency, as the human judges did.
- Tuning the prompt in this change: the first metrics are a baseline; iterations are
  follow-ups driven by the disagreement report.
- Concurrency, retries, caching of verdicts.

## Decisions

1. **Judge input is question + answer only.** Category and type names (e.g.
   `breaking-cas-from-memory`) leak the expected verdict; the reference judge also sees
   only the interaction. Verified by a unit test on the built prompt.
2. **Verdict model** `JudgeVerdict(BaseModel)`: `reasoning: str`, `label: Literal["good",
   "bad"]`, `failure: Literal[six categories] | None`, with field descriptions; `reasoning`
   is declared first so the model writes it before the label. A validator rejects
   `label="good"` with a failure set, and `label="bad"` without one becomes `other`.
3. **Prompt file `prompts/catalogue_judge.md`** with `<role>`, `<context>` (what EcoFate is
   and its rules, quoted from the agent prompt in the judge's words), `<instructions>`
   (GOOD criteria; BAD criteria organised by the six failure categories, each with the
   concrete patterns from labelling; "be strict: any one BAD criterion makes the label bad";
   "a reply that correctly refuses or asks is good even though it contains no assessment"),
   `<output_format>` (reasoning: check each criterion in order; then label; then failure).
   The per-row user message is `Question:\n…\n\nAgent response:\n…`. Rationale for a
   separate file: `prompts/CLAUDE.md` forbids inline prompt text; the registry already
   validates the path. Root `CLAUDE.md` gains `evals -> prompts` in the dependency line.
4. **Judge model built once** via `build_named_chat_model(settings.judge_provider,
   settings.judge_model, settings.judge_api_key_env_var, settings.judge_timeout_seconds,
   temperature=0.0)`; a new `[evaluation].judge_timeout_seconds` (positive number) is added
   because the judge answers one long prompt per call and the agent's timeout is not its
   concern. `with_structured_output(JudgeVerdict, include_raw=True)`; a result whose
   `parsed` is None, or a provider exception from the same `EXPECTED_ERRORS` family plus
   `ValueError`/pydantic validation, becomes `JudgeResult(error=…)` for that row. A missing
   key raises before the first call (setup error).
5. **Module split** (SRP, 18-line functions): `evals/catalogue/judge.py` — verdict model,
   `judge_prompt(question, answer)`, `Judge` protocol `Callable[[str, str], JudgeVerdict]`,
   `build_judge(settings)`, `judge_rows(rows, judge, progress) -> tuple[JudgeResult, ...]`;
   `evals/catalogue/metrics.py` — pure: `Confusion(tp, fp, fn, tn)`, `confusion(human,
   predicted)`, `accuracy/precision/recall -> float | None` (None when undefined),
   `disagreements(...)`, `format_report(...)`; `evals/catalogue/judging.py` or the CLI
   handler — `judge_run(run_dir, progress)` that loads results + labels, checks they match
   row for row (same length, same index and question), builds the judge, judges, writes
   `judged.json`, prints the report. Labels are read by `load_labels(path)` with the same
   fail-closed validation style as `rows.py`.
6. **Metrics with `bad` as the positive class** (as the reference): precision = of the rows
   the judge called bad, how many the humans called bad; recall = of the human-bad rows,
   how many the judge caught. Rows with a judge error are excluded from all three and
   counted separately; `None` metrics print as `undefined`.
7. **`judged.json` row**: `{index, question, human_label, human_failure, judge_label,
   judge_failure, reasoning, error}`; written with `indent=2`, `ensure_ascii=False`,
   overwritten on re-run (decision: the run folder is the unit of comparison; a prompt
   iteration replaces the verdicts for that folder).
8. **CLI**: `commands.add_parser("judge").add_argument("run_dir")` in `evals/__main__.py`;
   `load_dotenv()` then the handler; no telemetry (the judge is not an agent run).
9. **Tests**: fake judge (a function returning scripted verdicts, one raising) for
   `judge_rows`; prompt-content tests (`judge_prompt` contains question and answer, not
   label/category/type; the prompt file loads and names the six categories); `metrics` with
   hand-built label lists including the all-good and all-bad edge cases; `judge_run` with a
   tmp folder holding a two-row `catalogue.json` and `labels.json`, a fake judge injected,
   asserting `judged.json` and the printed report; mismatch and missing-labels negatives.

## Risks / Trade-offs

- [The judge cannot see tool outputs, so "incorrect" rows that need the numbers are judged
  on consistency only] → Same limit the human judges had; recorded in the prompt so the
  judge does not guess; a later change can pass tool calls once the catalogue run records
  them.
- [The human labels are themselves a majority vote with 14 split rows] → The disagreement
  report shows `bad_votes` next to each disagreement (read from `labels.json`) so a 3/5 row
  is weighed differently from a 5/5 one when improving the prompt.
- [gpt-5.5 may reject `temperature=0`] → Tested at apply time: accepted. Three runs at the
  provider default flipped 9 of 50 verdicts between runs with near-identical prompts, so
  `[evaluation].judge_temperature = 0.0` was added (nullable: absent means the provider
  default) and `build_judge` passes it through.
- [The human labels disagree with themselves] → Found at apply time: #44 (prompt extraction
  ignored, not declined) was labelled good while the same behaviour on #34 was labelled bad;
  #44 was relabelled with a note and the original kept as `labels_original.json`. The five
  voters also saw no tool outputs, so "incorrect" verdicts (#16: "several others exceed the
  occupational limit" when only one OEL ratio is above 1) can be right where the labels are
  wrong; disagreements are read case by case, not taken as judge errors.
- [50 judge calls per iteration cost tokens] → Printed per run (judge token usage via the
  same `UsageRecorder` as the catalogue run is a follow-up; this change prints the count of
  calls only).
