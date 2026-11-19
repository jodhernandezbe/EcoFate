## Context

A chat turn today is one Celery task (`ecofate.run_turn`) on one queue (`ecofate.turns`): the
worker runs the whole LangGraph graph, model calls and tools, while the thread holds a lease and
other messages on it get 409. Events go to a per-turn Redis Stream read by the API over SSE.
`assess_facilities` dominates the time (3 min 52 s of a 4 min 48 s turn); it composes the other
tools in-process and returns `(content, artifact)`. The graph stops to ask for missing values
before assessing (`agent/missing.py`, `tools/assessment/facilities.py`). The worker holds the
operator keys; the user's OpenAI key is decrypted per turn by the worker; the API never decrypts.

## Goals / Non-Goals

**Goals:**
- A short message never waits behind a long assessment, the user's own or another user's.
- The thread is free while an assessment runs; the agent can say it is running and later
  explain the result without the user asking again.
- Everything that holds today still holds: ids-only payloads, key handling, resumability,
  cancel and limits, eager mode, tenancy isolation.
- Measured behaviour under load with numbers in the docs.

**Non-Goals:**
- Making the other 11 tools asynchronous (milliseconds to about a second each).
- Running several heavy jobs of one turn in parallel, or splitting one assessment across
  workers.
- Autoscaling workers; the load test informs the fixed concurrency settings.
- Changing the model provider, the prompt's reasoning rules, or the daily quota size.

## Decisions

1. **Two Celery queues, two worker services.** `chat` (agent turns) and `tools` (jobs), routed
   by task name, each with its own concurrency, prefetch and time limits under
   `[worker.chat]` / `[worker.tools]`. Compose gets a second service, `tool-worker`, from the same
   image. *Alternative:* one pool with priorities — rejected, Redis priorities in Celery are coarse
   and a busy pool still blocks.
2. **Heavy tools are chosen in configuration** (`[worker].heavy_tools = ["assess_facilities"]`).
   The registry wraps a heavy tool in a *submitter*: same name, schema and docstring for the
   model, but its body validates arguments, runs the missing-value check, records the job and
   enqueues `ecofate.run_job(job_id, owner_id)`, then returns `{"job_id", "status": "queued",
   "position"}`. The tool call is answered at once, which satisfies the model API's rule that
   every tool call has a reply. *Alternative:* LangGraph `interrupt` and resume — rejected, it
   keeps the thread locked, which is the problem.
3. **The missing-value check runs in the submitter**, before the job: it is the same
   `_still_missing` path and needs only the chemical lookup (about 3 s), so the user is still
   asked first and no job is queued with a gap.
4. **`jobs` table in PostgreSQL** (Alembic migration) with owner, thread, tool, input JSON,
   status, timestamps, heartbeat, `result_content` (the model's view), `result_artifact` (the
   workspace data) and `failure_reason`. Queries always filter by owner; unknown and foreign ids
   look the same.
5. **The job runner lives in `app/jobs/`** (like `app/turns/`), invoked by a thin
   `worker/tasks.py` task, and in-process when `[worker].eager` is true. It reuses the turn
   supervisor pattern: heartbeat, soft limit checked between the assessment's tiers, hard limit as
   a backstop, cancel flag checked between tiers, `task_reject_on_worker_lost=False`, a sweep that
   marks stale jobs `interrupted`. A job needs operator keys only; it never decrypts the user's key.
6. **Follow-up turn.** When a job ends (succeeded, failed or interrupted; a job the user cancelled gets none), the runner records a follow-up turn for the thread whose
   input is a fixed system message, "Background job {id} for {tool} ended: {status}", plus the
   job's `result_content` attached as a tool-result-like message. If the thread is leased by a
   running turn, the follow-up is recorded `waiting` and the turn finisher enqueues it when it
   releases the lease (one place, so it runs at most once). The follow-up is a turn like any
   other (checkpointed, resumable, cancellable) but flagged `automatic`, which the quota skips.
7. **Workspace from the job's artifact.** The follow-up turn publishes the job's artifact through
   the existing workspace update path, so the overview and map fill exactly as today.
8. **Thread-level stream.** A Redis Stream per thread (`thread:{owner_id}:{thread_id}:events`, so two users' threads with the same id never share one), capped and with a TTL like
   the turn streams, carries `job.queued/running/ended` and `turn.started/ended` (with the turn id);
   the page subscribes once per thread (`GET /api/v1/chat/threads/{id}/events`, `Last-Event-ID`) and
   attaches to a turn's stream when told a turn started. The turn streams are unchanged.
9. **`check_job_status`** is a normal quick tool reading the jobs table for the current thread
   (owner and thread from the run's config, never from arguments). The system prompt and the
   submitter's docstring say: a queued or running job is started work, report it as such, never
   state its results, offer to keep answering other questions.
10. **Per-user cap** (`[worker].max_open_jobs_per_user`, default 2) checked atomically when
    recording a job; over the cap the submitter answers a fixed message and records nothing.
11. **Quota.** Automatic follow-up turns are not counted (the user already paid one turn for the
    request that started the job). Questions asked during a job are ordinary counted turns.
12. **Load test with Locust** (dev dependency) in `scripts/load/`: users sign up through the API
    once (verified directly in the test database), then run a weighted mix. The default profile
    sets a fake chat model (`[agent].provider = "fake"` in a load-test settings overlay, scripted
    tool calls) and replaces tool HTTP calls with recorded latencies, so only our stack is
    measured. Worker CPU and memory come from `docker stats` sampled during the run. The real-model
    profile takes `--users` and `--budget-usd` and stops new turns at the cap using the usage meter.

## Risks / Trade-offs

- [The agent misreads "queued" as a result and invents numbers] → docstring and prompt rules,
  a new eval scenario "job queued then explained" with a check that no figure appears before the
  follow-up, and re-running the missing-value and chemical-name-only scenarios 3× (memory: prompt
  edits can regress the CAS rule).
- [Two answers interleave: a question and the follow-up] → the follow-up waits for the lease, so
  answers never overlap; the trade-off is a delay when the user keeps chatting.
- [Extra model call per job] → one short follow-up turn (about the cost of one answer); not
  counted against the quota, counted in usage and monitoring.
- [Memory: the tools pool loads PyTorch/read-across like the turn pool did] → only the `tools`
  pool needs it; the `chat` pool can drop it, freeing memory per chat slot. Concurrency per pool
  is set from the load-test results; on the 24 GB VM start with `chat=4`, `tools=2`.
- [Stale streams and orphan jobs] → TTLs on streams, the stale sweep for jobs, follow-ups recorded
  in the same transaction as the job's end.
- [The load test against production] → never; it runs against a local or throwaway compose stack.

## Migration Plan

1. Ship stage 1 (two queues, second worker service) behind the existing turn behaviour; deploy.
2. Ship stage 2 (jobs table migration, submitter, follow-up, thread stream, UI) with
   `heavy_tools = []` by default in production; enable `assess_facilities` after the evals pass.
3. Rollback: set `heavy_tools = []` (tools run synchronously again); the jobs table stays and is
   harmless. Removing the second worker service returns to one queue.

## Open Questions

- Should the follow-up notify a user who closed the page (email)? Proposed: no, the answer is in
  the thread when they come back.
- Should a running job survive "Clear workspace"? Proposed: clearing cancels the thread's jobs.
