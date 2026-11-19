[← Documentation index](../../README.md#documentation) · [Evals](../README.md)

# The catalogue and its labels

## The catalogue

`evals/catalogue/scenarios.csv` holds 50 questions written by hand (columns `question,category,type`),
each tied to a rule in the system prompt or a tool contract. The design is in
`openspec/changes/archive/2026-11-02-add-eval-scenario-catalogue/`. Types, counted from the file:

| Type | Questions |
|---|---|
| `happy_path` | 10 |
| `varied_phrasing` | 10 |
| `edge_case` | 15 |
| `out_of_scope` | 6 |
| `breaking` | 9 |

The `breaking` rows attack one rule each (a CAS number from memory, a silent CAS correction, a
prompt injection, prompt extraction, an invented identifier, an unsupported compartment, a category
value reported as measured, an analogue below the threshold, an invented default). The file holds
no expected answers. A shape test (`tests/evals/catalogue/test_rows.py`) runs in pre-commit.

`uv run python -m evals catalogue` sends every question to the live agent, one turn each, by the same
path as `python -m app` (stored keys, step limit, metered usage), and saves each answer with its
execution time, token counts and estimated cost (from `[ui.pricing]`) to
`evals/reports/<timestamp>/catalogue.json`. A row that fails on the step limit or a service error is
recorded with the error and the run continues.

## Labels

`labels.json` (next to `catalogue.json`) has one object per row: `index`, `question`, `category`,
`type`, `label` (`good` or `bad`), `bad_votes` out of `judges` (5 for every row), `failure`
(one of `rule-break`, `wrong-scope`, `incomplete`, `incorrect`, `hallucination`; null when good),
`failure_votes` and `reasons`.

How the labels for run `20261102-195041` were produced, from what the repository records:

- Each of the 50 answers was voted on by five judges, and the label is the majority (`bad_votes` of
  5; the archived design calls it "the five-judge vote" and "five-judge majority"). 36 rows were
  unanimous and 14 were split.
- The reasons stored with each row refer to the "prompt rules" and to what "the category implies", so
  the voters judged against the system prompt's rules and the row's category. They saw no tool
  outputs (stated in `openspec/changes/archive/2026-11-07-add-catalogue-llm-judge/design.md`).
- Who the five voters were (people, models or a mix) and how they were recorded is **not recorded**
  in the repository. Neither is the exact instruction they were given.
- The vote found 18 bad answers of 50 and four recurring failure patterns (the CAS rule breaking
  under pressure, domain-flavoured off-topic requests being performed, values asked for that the
  requested result does not use, and bookkeeping slips on large fan-outs).
- One label was corrected afterwards: row 44 (the prompt-extraction question) was labelled good
  although the same behaviour on row 34 was labelled bad, so it was relabelled bad with a note and
  the original kept as `labels_original.json`. `labels.json` therefore has 19 bad answers: 10
  `rule-break`, 3 `incomplete`, 3 `wrong-scope`, 2 `incorrect` and 1 `hallucination`.

`evals/reports/` is git-ignored (`.gitignore`: "Generated agent-evaluation reports"), so these
files exist on the author's machine and are not part of a fresh clone.
