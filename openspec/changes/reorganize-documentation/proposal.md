## Why

The README (198 lines) grew one feature at a time: the problem statement is three lines,
the tool reference is a wall of paragraphs, the evaluation work (14 scripted scenarios, a
50-question hand-written catalogue, human labels, an LLM judge tuned over six iterations from
68% to 78% accuracy) is described as commands rather than results, and nothing shows the app
running. The capstone is graded by two readers with different needs (Documentation Tips):
peers who score every criterion and may try to reproduce it, and hiring managers who scan
for one or two minutes. Neither can find the evidence for each criterion quickly, and there
is no self-evaluation. After ROADMAP steps 1-9 the README also has to cover Docker,
accounts, BYOK, the worker, CI and the deployment.

## What Changes

- **README rewritten in two layers.**
  - *The 2-minute scan* (top, one screen or two): one-sentence pitch, CI badge, the live URL
    or demo video/GIF, a screenshot of a user prompt and the agent's answer with the
    dashboard, the problem in plain words, "what it does" in three bullets, a highlights
    table (tools, knowledge base, tests, evaluation result, monitoring, Docker, CI/CD, cloud),
    the headline evaluation numbers, a screenshot of the admin Monitoring view, and a
    `docker compose up` quick start.
  - *For reviewers*: one section per capstone criterion, in the rubric's order, each saying
    what was built, where the code is, how to run or check it, and linking to the detail in
    `docs/`: Problem description; Knowledge base and retrieval; Agent, LLM and tools;
    Code organization; Testing (unit tests and judge tests, how to run each); Evaluation
    (hand-crafted ground truth, manual labelling, LLM judge, tuning iterations with their
    numbers, how to run); Monitoring (what is logged, how logs are processed, how to open the
    dashboard, user feedback if built); Reproducibility (prerequisites, keys, `docker compose
    up`, `uv` path, where the data comes from and that it is in the repository); Best
    practices (Docker, compose, Makefile, uv, CI/CD, pre-commit gates, security); Deployment.
  - *Self-evaluation* at the end: a table with every criterion and bonus item, the score
    claimed, and a link to the evidence; items not met are listed as not met.
- **Detail moved to `docs/`**, each file self-contained and linked from the README:
  `architecture.md` (layers, dependency rules, runtime diagram of the compose services and a
  turn's path through api → worker → agent → tools), `tools.md` (today's tool reference,
  moved verbatim then tidied), `evaluation.md` (datasets, how they were made, labelling
  procedure, judge prompt iterations table, model/prompt tuning decisions, how to
  reproduce), `monitoring.md` (Logfire set-up, what a session records, redaction, admin
  dashboard), `deployment.md` (from `add-cloud-deployment`), `security.md` (BYOK, key
  encryption, tenancy isolation, redaction, rate limit, threat model summary, how secrets
  are handled in CI and production). Existing `docs/design-principles.md` and the UI audits
  stay; a `docs/README.md` index lists every file.
- **Screenshots and a short demo** under `docs/images/` captured from the running app
  (sign-in, prompt and answer with dashboard and map, progress while a turn runs, resume
  after an interruption, evaluation report/judge output, admin Monitoring list and session
  detail), each with alt text, PNG under 500 KB (the pre-commit large-file limit is 1000 KB),
  plus a GIF or a linked video of one full assessment.
- **Evaluation results checked in as evidence**: a compact `docs/evaluation-results.md` (or
  a section of `evaluation.md`) generated from `evals/reports/20261102-195041/` with the
  per-iteration judge accuracy/precision/recall, and the latest scenario-run pass rate.
- **Link check**: a test `tests/test_docs_links.py` that parses every relative link and image
  in `README.md` and `docs/*.md` and fails when a target file or heading anchor does not
  exist; it runs in the default pytest suite (and so in pre-commit and CI).
- `CLAUDE.md` gains one line pointing to `docs/README.md` (within the 80-line budget).

## Capabilities

### New Capabilities

- `project-documentation`: what the README and `docs/` must contain for the two target
  readers, the per-criterion reviewer sections, the self-evaluation, the screenshots, and
  the link check.

### Modified Capabilities

(none)

## Impact

- `README.md` (rewritten), new `docs/{README,architecture,tools,evaluation,monitoring,security}.md`,
  `docs/deployment.md` extended (created by `add-cloud-deployment`), `docs/images/*`,
  `tests/test_docs_links.py`, root `CLAUDE.md` (one line).
- No change to application code. Screenshots need the running stack and an OpenAI key once
  (a few cents); the judge numbers come from existing reports, no new token spend is needed.
- Folder `CLAUDE.md` files and the per-change README edits made by steps 1-9 are kept;
  this change reorganises, it does not re-describe features that changed.
