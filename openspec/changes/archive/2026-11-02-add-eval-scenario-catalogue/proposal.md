## Why

The evaluation harness in `evals/` runs four scripted scenarios and lists ten more as
placeholders ("checks and cassette not written yet"). That covers the happy path and three
gaps, but nothing systematic: no varied phrasing from the three user groups (risk assessors,
public health researchers, community advocates), no out-of-scope or prompt-injection probes,
and no scenarios built to make the agent fabricate a CAS number, a facility ID, a wind rose or
a water-pathway result. A reviewed catalogue of 50 questions, each tied to a rule in the system
prompt or a tool contract, is the input the harness needs before more cassettes are recorded.

## What Changes

- Add `evals/scenarios.csv`: 50 evaluation questions specific to EcoFate, with columns
  `question`, `category`, `type` where `type` is one of `happy_path`, `varied_phrasing`,
  `edge_case`, `out_of_scope`, `breaking`.
- Each question targets a concrete behaviour of this agent (the CAS-only identification rule,
  TRI category membership, read-across threshold, stack tiers, facility coverage, missing-value
  confirmation, scope guardrail, air-only compartments, no invented numbers), never a generic
  chatbot probe.
- At least 5 `breaking` scenarios designed to induce hallucination or rule breaks (recalling a
  CAS from memory, inventing a facility ID or wind rose, following injected instructions,
  computing a water or soil result, confirming a user-supplied wrong number).
- Document in `evals/CLAUDE.md` that the CSV is the question catalogue reviewed before a
  scenario gets checks and a cassette in `evals/scenarios.py`.
- No code runs; no cassettes are recorded; `evals/scenarios.py` is untouched.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `agent-evaluation`: adds a requirement that the evaluation keeps a reviewed catalogue of
  scenario questions covering the five scenario types, with the question, its category and
  its type, from which scripted scenarios are drawn.

## Impact

- `evals/scenarios.csv` (new data file), `evals/CLAUDE.md` (one bullet).
- No runtime, API, frontend or dependency changes. Pre-commit hooks that read source packages
  are unaffected (CSV is not a Python source file); `detect-secrets` scans it like any file.
- Follow-up work (out of scope here): turning catalogue rows into `Scenario` entries with
  checks, judges and recorded cassettes.
