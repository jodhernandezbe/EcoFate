## 1. Link check first

- [ ] 1.1 Write `tests/test_docs_links.py`: collect `README.md` and `docs/**/*.md`; parse inline links and images (`[t](target)`, `![a](target)`); for relative targets assert the file exists; for `#anchor` (same file or `file.md#anchor`) assert a heading with that GitHub slug exists; skip `http(s)://` and `mailto:`; include negative tests with a tmp Markdown file (missing file, missing anchor).

## 2. docs/ files

- [ ] 2.1 `docs/architecture.md`: package layers and dependency rules (from root `CLAUDE.md`), a diagram of the compose services (api, worker, db, redis, mailpit, caddy) and a turn's path (browser → api → Redis → worker → agent → tools → models; progress back over SSE), where state lives (Postgres tables, checkpoints), configuration vs. secrets.
- [ ] 2.2 `docs/tools.md`: move the README "Tools" section verbatim, then add a summary table (tool, input, output, data source, key needed, limits) above the per-tool notes.
- [ ] 2.3 `docs/evaluation.md`: the scripted scenarios (14, cassettes, deterministic checks, Evidently judges); the catalogue (50 hand-written questions, categories and types, why hand-written); labelling procedure for `labels.json` stated exactly as it was done; the LLM judge (inputs, verdict, prompt file); the tuning iterations table with accuracy/precision/recall per prompt version and what changed in each, numbers recomputed from `evals/reports/20261102-195041/judged_*.json` with the file named; agent prompt/model tuning decisions with their eval evidence; how to reproduce each step and its cost.
- [ ] 2.4 `docs/monitoring.md`: Logfire set-up (write/read tokens by the operator), what a session span holds, how logs are processed (spans → Logfire query API → `api/services/monitoring/` → admin view), redaction, how an admin opens the dashboard locally and in production, screenshots.
- [ ] 2.5 `docs/security.md`: BYOK (only the OpenAI key from the browser; operator keys in the environment), AES-GCM key storage with user-id AAD, tenancy isolation (404 on foreign ids), sessions and password recovery, daily rate limit, log/span/task-payload redaction, CI and production secret handling, how to report a vulnerability.
- [ ] 2.6 `docs/README.md`: index of every docs file (including `design-principles.md`, the UI audits and `deployment.md`) with one line each.

## 3. README

- [ ] 3.1 Scan layer (about 80 lines max): title, pitch, CI badge, live URL or demo GIF/video, prompt-and-answer screenshot, the problem (who, what is hard today, what EcoFate does), three "what it does" bullets, highlights table, headline evaluation numbers (judge 78% accuracy / 0.95 recall vs. human labels; latest scenario pass rate), Monitoring screenshot, `docker compose up` quick start.
- [ ] 3.2 Reviewer sections in rubric order, each with what / where (code links) / check it (command) / details link: Problem description; Knowledge base and retrieval; Agent, LLM and tools; Code organization (tree + layer rules); Testing (unit, smoke, frontend, judge tests, exact commands); Evaluation; Monitoring; Reproducibility (prerequisites, keys and which are operator vs. user, `docker compose up`, `make` targets, `uv` path, data in `data/` and rebuild scripts); Best coding practices (Docker, compose, Makefile, uv, CI/CD, pre-commit gates); Deployment (URL or recording, link to `docs/deployment.md`).
- [ ] 3.3 Self-evaluation table at the end: every criterion and bonus item, max points, claimed points, evidence links; unmet items shown as 0 with a link to the ROADMAP backlog. Fill it from what is merged at the time.
- [ ] 3.4 Root `CLAUDE.md`: one line pointing to `docs/README.md`; confirm `tests/test_claude_md.py` still passes.

## 4. Screenshots and demo

- [ ] 4.1 With `docker compose up` and a demo account, capture into `docs/images/`: sign-in, prompt + answer with dashboard and map, progress during a turn, resume after an interruption, OpenAI-key settings showing only status, admin Monitoring list and a session detail, an evaluation report / judge output. 1440×900, light theme, cropped, each PNG under 500 KB; no key, token or personal email visible.
- [ ] 4.2 Record one full assessment as a GIF under 1000 KB (or upload a video and link it); add `docs/images/README.md` listing each image, the screen and how to reproduce it.

## 5. Verification

- [ ] 5.1 `uv run pytest tests/test_docs_links.py tests/test_claude_md.py` and `uv run pre-commit run --all-files` pass (large-file and detect-secrets hooks clean on the images and docs).
- [ ] 5.2 Read the README top as a hiring manager (two screens: problem, demo, evaluation, monitoring visible) and as a reviewer (each rubric criterion findable from the table of contents); fix gaps.
- [ ] 5.3 Run the course project scorer (module 5 evaluator agent) on the repository and compare its scores with the self-evaluation; note any difference.
