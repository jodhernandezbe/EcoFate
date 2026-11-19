## 1. Two queues (stage 1)

- [x] 1.1 `config/`: `[worker.chat]` and `[worker.tools]` (queue name, concurrency, prefetch, soft/hard limits), `heavy_tools`, `max_open_jobs_per_user`; loader validation and negative tests (limits out of order, unknown heavy tool, bools as numbers).
- [x] 1.2 `app/task_queue.py`: route `ecofate.run_turn` to `chat` and `ecofate.run_job` to `tools`; tests that each task name goes to its queue and payloads stay ids only.
- [x] 1.3 `worker/`: start each pool on its queue; `compose.yaml` and `compose.prod.yaml` gain a `tool-worker` service from the same image; `make worker-logs` covers both.
- [x] 1.4 Docs: `worker/README.md`, `docs/architecture.md`, and the `containers` and `turn-sequence` draw.io diagrams updated.

## 2. Jobs (stage 2)

- [x] 2.1 `storage/`: `jobs` table and Alembic migration; a job store with owner-scoped reads, atomic per-user cap, status transitions, heartbeat; PostgreSQL tests (`postgres` marker) and in-memory store tests.
- [x] 2.2 `app/jobs/`: the job runner (queued → running → ended, heartbeat, soft limit between assessment tiers, cancel flag, hard limit backstop, failure reasons without secrets) and the stale sweep; in-process runner for eager mode; tests with the memory bus.
- [x] 2.3 `worker/tasks.py`: `ecofate.run_job(job_id, owner_id)` validating its ids; operator keys only; `task_failure` marks the job `interrupted`.
- [x] 2.4 `tools/`: the heavy-tool submitter (same name, schema and docstring) that runs the missing-value check, records and enqueues the job and answers `{job_id, status, position}`; over-cap message; `check_job_status` tool (owner and thread from config); registry, registry test and tool tests.
- [x] 2.5 `app/turns/`: follow-up turns (recorded when a job ends, `waiting` while the thread is leased, enqueued once by the turn finisher, flagged `automatic`), workspace filled from the job's artifact; tests for idle thread, busy thread, at-most-once.
- [x] 2.6 Quota: automatic follow-ups not counted; tests.
- [x] 2.7 Thread-level stream: `thread:{id}` Redis Stream, `GET /api/v1/chat/threads/{id}/events` with `Last-Event-ID`; job and turn lifecycle events; tests for reconnect and tenancy (foreign thread 404).
- [x] 2.8 API: cancel a job (`POST /api/v1/chat/jobs/{id}/cancel`), job status in the workspace response; `Clear workspace` cancels the thread's jobs.
- [x] 2.9 Frontend: subscribe to the thread stream; a job status line under the chat header ("Assessment queued (2 ahead)", "Assessment running, 1 min 20 s", Cancel), sending allowed while a job runs; the follow-up answer appears as a normal message; DESIGN.md-compliant; `/ui-check`.
- [x] 2.10 Prompt and docstrings: how to talk about a queued or running job; never state its results before the follow-up. (Measured in 3.2: a system-prompt paragraph about it weakened the CAS rule, so the guidance lives only in the submitter's note and `check_job_status`'s docstring.)

## 3. Evaluations

- [x] 3.1 New scenario "assessment queued then explained": the agent reports the job as started, states no figures, and the follow-up explains the result; cassette recorded.
- [x] 3.2 Re-record and re-run the missing-value and chemical-name-only scenarios 3× each; keep the change only if they pass.

## 4. Load test

- [x] 4.1 `scripts/load/`: Locust users (sign-up/verify once, weighted mix: full assessment, question during a job, status question, resume), a load-test settings overlay with the fake chat model and recorded tool latencies, `docker stats` sampler, report writer (percentiles of time to first answer, queue wait per queue, job and turn duration; 409/429/5xx shares; CPU and memory).
- [x] 4.2 Run at 10, 25 and 50 users with the fake model on the local compose stack; then tune `[worker.chat]`/`[worker.tools]` concurrency from the results.
- [x] 4.3 Real-model run at about 10 users with a budget cap the owner sets (stated before running).
- [x] 4.4 `docs/load-test.md`: stack, settings, date, commands, the measurements of each run and a short reading of where the limit is; indexed from the root README and `docs/README.md`.

## 5. Release

- [x] 5.1 All checks (`uv run pre-commit run --all-files`), security audit, version bump.
- [x] 5.2 Deploy stage 1, then stage 2 with `heavy_tools = []` in production; enable `assess_facilities` after 3.2 passes and verify one assessment at https://ecofate.org (job queued, a question answered meanwhile, the follow-up explains the result).
