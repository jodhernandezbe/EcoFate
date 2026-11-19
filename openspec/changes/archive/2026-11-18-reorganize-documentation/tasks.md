## 1. Link check first

- [x] 1.1 Write `tests/test_docs_links.py`: collect every tracked `README.md` (outside `node_modules`, `.venv`, `.claude`) and `docs/**/*.md`; parse inline links and images (`[t](target)`, `![a](target)`); for relative targets assert the file exists; for `#anchor` (same file or `file.md#anchor`) assert a heading with that GitHub slug exists; skip `http(s)://` and `mailto:`; include negative tests with a tmp Markdown file (missing file, missing anchor).

## 2. Folder READMEs and docs/ files

- [x] 2.1 `docs/architecture.md`: package layers and dependency rules (from root `CLAUDE.md`), the runtime services (api, worker, db, redis, mailpit locally; cloudflared in production) and a turn's path, where state lives (Postgres tables, checkpoints), configuration vs. secrets; embeds the three high-level diagrams.
- [x] 2.2 `tools/README.md`: move the README "Tools" section verbatim, then add a summary table (tool, input, output, data source, key needed, limits) above the per-tool notes; "Adding a tool"; embeds the batch-assessment diagram.
- [x] 2.3 `evals/README.md`: the scripted scenarios (cassettes, deterministic checks, Evidently judges); the catalogue (50 hand-written questions); the labelling procedure for `labels.json` exactly as it was done; the LLM judge; the tuning iterations table (accuracy/precision/recall per prompt version and what changed) recomputed from `evals/reports/20261102-195041/judged_*.json` with the file named; prompt/model tuning decisions with their eval evidence; how to reproduce and its cost; embeds the evaluation-pipeline diagram.
- [x] 2.4 `agent/README.md` (graph, nodes, guards, asking for missing values, swapping the LLM provider; agent-graph diagram), `models/README.md` (equations and units), `prompts/README.md` (prompt files and registry), `config/README.md` (settings files, production override, how to add a setting).
- [x] 2.5 `api/README.md` (endpoints, accounts and email, BYOK, daily limit, SSE), `worker/README.md` (Redis/Celery, resumable turns; turn-sequence diagram), `storage/README.md` (tables, Alembic, checkpoints), `frontend/README.md` (workspace, what it shows and does not, how to run and test; links `DESIGN.md`).
- [x] 2.6 `deploy/README.md` (what each script does; links `docs/deployment.md`; release-and-rollback diagram), `docs/monitoring.md` (Logfire set-up with both tokens, what a session span holds, spans → query API → `api/services/monitoring/` → admin view, redaction, opening the dashboard locally and in production), `docs/security.md` (BYOK, AES-GCM key storage with user-id AAD, tenancy isolation, sessions and password recovery, daily rate limit, redaction, CI and production secret handling, reporting a vulnerability).
- [x] 2.7 `docs/README.md`: index of every docs file (including `design-principles.md`, the UI audits and `deployment.md`). Every document from 2.1-2.6 starts with the navigation line back to the root index and has a table of contents past three sections.

## 2b. draw.io diagrams

- [x] 2b.1 High level in `docs/diagrams/`: `system-context.drawio.svg`, `containers.drawio.svg`, `package-layers.drawio.svg` (dependency arrows exactly as in root `CLAUDE.md`).
- [x] 2b.2 Low level: `agent-graph.drawio.svg` (nodes and edges from `agent/graph.py`), `turn-sequence.drawio.svg` (browser → api → Redis → worker → agent/tools → event stream → SSE, resume), `batch-assessment.drawio.svg` (bound → own stacks → full assessment, and the tools it invokes), `evaluation-pipeline.drawio.svg`, `release-rollback.drawio.svg` (tag → CI images → GHCR → approval → SSH via tunnel → deploy.sh → health check → rollback).
- [x] 2b.3 Each file opens in draw.io (embedded diagram) and renders on GitHub; each is embedded with alt text and a caption naming the source files it was drawn from; every named element verified in the code.

## 3. README

- [x] 3.1 (the root README stays an index; the scan content is `docs/demo.md`) Scan layer (about 80 lines max): title, pitch, CI badge, live URL or demo GIF/video, prompt-and-answer screenshot, the problem (who, what is hard today, what EcoFate does), three "what it does" bullets, highlights table, headline evaluation numbers (judge 78% accuracy / 0.95 recall vs. human labels; latest scenario pass rate), Monitoring screenshot, `docker compose up` quick start.
- [x] 3.0 Documentation index section (grouped: use it, understand it, extend it, operate it) linking every folder README and `docs/` file.
- [x] 3.2 (as `docs/reviewers.md`, one table; the root README is an index of short pages, with `DEVELOPMENT.md` at the root for developers and long documents split into subpages under `docs/security/`, `docs/deployment/`, `api/docs/`, `evals/docs/`; no text diagrams, only draw.io) Reviewer sections in rubric order, each with what / where (code links) / check it (command) / details link: Problem description; Knowledge base and retrieval; Agent, LLM and tools; Code organization (tree + layer rules); Testing (unit, smoke, frontend, judge tests, exact commands); Evaluation; Monitoring; Reproducibility (prerequisites, keys and which are operator vs. user, `docker compose up`, `make` targets, `uv` path, data in `data/` and rebuild scripts); Best coding practices (Docker, compose, Makefile, uv, CI/CD, pre-commit gates); Deployment (URL or recording, link to `docs/deployment.md`).
- [x] 3.3 Self-evaluation table at the end: every criterion and bonus item, max points, claimed points, evidence links; unmet items shown as 0 with a link to the ROADMAP backlog. Fill it from what is merged at the time.
- [x] 3.4 Root `CLAUDE.md`: one line pointing to `docs/README.md`; confirm `tests/test_claude_md.py` still passes.

## 4. Screenshots and demo

- [x] 4.1 With `docker compose up` and a demo account, capture into `docs/images/`: sign-in, prompt + answer with dashboard and map, progress during a turn, resume after an interruption, OpenAI-key settings showing only status, admin Monitoring list and a session detail, an evaluation report / judge output. 1440×900, light theme, cropped, each PNG under 500 KB; no key, token or personal email visible.
- [x] 4.2 (done as `docs/demo.md`: a screenshot walk-through with the story, which the course accepts instead of a video; no GIF) Record one full assessment as a GIF under 1000 KB (or upload a video and link it); add `docs/images/README.md` listing each image, the screen and how to reproduce it.

## 5. Verification

- [x] 5.1 `uv run pytest tests/test_docs_links.py tests/test_claude_md.py` and `uv run pre-commit run --all-files` pass (large-file and detect-secrets hooks clean on the images and docs).
- [x] 5.2 Read the README top as a hiring manager (two screens: problem, demo, evaluation, monitoring visible) and as a reviewer (each rubric criterion findable from the table of contents); fix gaps.
- [x] 5.3 (dropped: the course scorer is an optional suggestion of the course, not a requirement) Run the course project scorer (module 5 evaluator agent) on the repository and compare its scores with the self-evaluation; note any difference.
