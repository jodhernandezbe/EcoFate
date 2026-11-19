[← Documentation index](../../README.md#documentation) · [Evals](../README.md)

# Scripted scenarios and prompt decisions

## Scripted scenarios

`uv run pytest -m eval` runs the agent with the `[agent]` model on the scenarios in
`evals/scenarios.py`, checks its tool calls in code, and scores its reply with an LLM judge
(`[evaluation].judge_model`) through Evidently. An HTML report is written to `evals/reports/`.
Network tools are replayed from `evals/cassettes/` (a missing recording fails closed). Evaluations need
`OPENAI_API_KEY`, cost tokens, and are excluded from the default `pytest` run.

`evals/scenarios.py` lists 14 scenarios; four are written and runnable, ten are placeholders
blocked with a reason ("checks and cassette not written yet" or a fix they wait for).

| Scenario | Checks (code) | Judge | Cassette |
|---|---|---|---|
| `chemical-name-only` | completed, no tool called | asks for a CAS number without inventing one | none (no tool runs) |
| `missing-benchmark-asks` (acrolein) | completed, properties fetched, exposure not called, asks for the missing `iur` | none | `missing-benchmark-asks.json` |
| `full-assessment-with-nei-stacks` | every facility covered and reported, sources named, site inputs per facility, exposure covers every stack, no fallback where candidates exist | complete assessment report | `full-assessment-with-nei-stacks.json` |
| `category-member-chlorophenol` | completed, category looked up, inventory queried for category N084 | category match disclosed | `category-member-chlorophenol.json` |

Checks take their expected values from the record's tool outputs, never from numbers written into
the check. Recording a cassette runs the scenario once against the live services (it needs the
CompTox and Census keys too) and saves every network tool output; never edit a cassette by hand.

## Prompt and model decisions

Decisions taken from evaluation evidence, as recorded in the archived designs under `openspec/`:

- **The chemical-name-only regression** (`2026-10-20-add-tri-read-across-surrogate/design.md`, item 12):
  registering the read-across tool made the agent recall a CAS number (50-00-0) from the name
  "formaldehyde" about half the time. Measured on the first model turn, 30 samples per condition:
  8-16 of 30 clean with the tool and the old prompt, 2 of 30 after rewording only the tool
  description, and 30 of 30 in five batches with the clarified system prompt. A paraphrase of the same
  rule fell to 12 of 30, so the measured wording is pinned by a prompt test.
- **Agent temperature 0** (same design, item 13): `[agent].temperature = 0` for reproducibility; it is
  not fully deterministic for gpt-4.1.
- **Tool descriptions are tested too.** In `2026-11-14-refine-worker-exposure-screening/design.md`,
  describing new result fields in a tool description dropped the chemical-name-only evaluation from
  10 of 10 to 1 of 10, so the description was left unchanged and the model learns of the new fields
  from the result's `note`. In `2026-11-17-worker-band-and-turn-controls/design.md`, a reworded
  docstring sentence gave 9 of 10 and was not kept.

Rule of thumb that follows: measure the chemical-name-only evaluation repeatedly before keeping any
prompt or tool-description edit.
