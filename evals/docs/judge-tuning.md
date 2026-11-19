[← Documentation index](../../README.md#documentation) · [Evals](../README.md)

# The LLM judge and its tuning

## The LLM judge

`uv run python -m evals judge evals/reports/<timestamp>` labels every answer with the LLM judge and
compares the verdicts with `labels.json`.

- The judge sees only the question and the answer, never the human label, the category or the type
  (so category names cannot leak the verdict). It returns structured output: `reasoning` first, then
  `label` (good or bad) and a `failure` category.
- The criteria are in `prompts/catalogue_judge.md`; the model is `[evaluation].judge_model`
  (`gpt-5.5-2026-04-23`), at temperature 0 (`judge_temperature`). At the provider's default
  temperature, three runs flipped 9 of 50 verdicts, which is why it is pinned to 0.
- It prints accuracy, precision and recall with `bad` as the positive class, the confusion matrix and
  every disagreement with the judge's reasoning, and writes `judged.json`. A failed judge call is an
  error, never a label.
- The loop is: run the catalogue, label it, judge it, read the disagreements, edit the judge prompt,
  judge again. A disagreement is not always a judge error: the labellers saw no tool outputs, so an
  "incorrect" verdict can be right where the label is wrong (for example row 16).

## Judge iterations

Recomputed from `evals/reports/20261102-195041/judged_baseline.json`, `judged_iter1.json` ...
`judged_iter6.json` (each row carries its `human_label` and `judge_label`; 50 rows, no judge errors),
with a one-off script that counts the confusion matrix per file. `bad` is the positive class.

| File | Accuracy | Precision | Recall | Human-bad rows in the file | What changed |
|---|---|---|---|---|---|
| `judged_baseline.json` | 0.68 | 0.53 | 1.00 | 18 | first prompt |
| `judged_iter1.json` | 0.70 | 0.55 | 0.94 | 18 | not recorded |
| `judged_iter2.json` | 0.68 | 0.53 | 1.00 | 18 | not recorded |
| `judged_iter3.json` | 0.66 | 0.51 | 1.00 | 18 | not recorded |
| `judged_iter4.json` | 0.72 | 0.58 | 1.00 | 19 | worker-tier clarification |
| `judged_iter5.json` | 0.74 | 0.59 | 1.00 | 19 | not recorded |
| `judged_iter6.json` (same figures as `judged.json`) | 0.78 | 0.64 | 0.95 | 19 | temperature 0 and false-positive clauses |

Notes:

- The first four files embed the 18-bad labels from before row 44 was corrected, and the last three
  the 19-bad labels; the metrics use the labels stored in each file.
- Only iterations 4 and 6 have a description in the repository (the planning notes of this
  documentation change); the prompt's intermediate versions were not committed, only the final
  `prompts/catalogue_judge.md`.
- On the 36 rows where all five voters agreed, the iteration-6 judge scores accuracy 0.89, precision
  0.78 and recall 1.00 (recomputed from `labels.json` and `judged_iter6.json`; the commit message of
  the judge, `1d866e7`, quotes the same figures). Over all 50 rows the last run has 11
  disagreements: 10 rows labelled good that the judge called bad and 1 labelled bad that it called
  good; the full list is in `judged.json`.
- The errors are mostly false positives (10 of 50 rows): the judge is stricter than the
  labellers, which suits a regression signal that must not miss a bad answer (recall 0.95).
