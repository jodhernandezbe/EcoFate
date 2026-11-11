## Why

An assessment turn runs for minutes (dozens of model calls, Census, CompTox, NEI and
read-across lookups). Today it runs inside the FastAPI request that streams it: the turn dies
with the HTTP connection or the API process, a reload loses the live progress, one API
process holds every running turn in its event loop, and a deploy kills turns in flight. In a
multi-user deployment the agent work must run in a separate, bounded worker pool, while the
user keeps seeing what is happening step by step.

## What Changes

- New package `worker/` with a Celery app (Redis broker and result backend, service `redis`
  and a `worker` service in docker compose, same image as `api`). One task,
  `ecofate.run_turn(turn_id)`, runs a new or resumed turn.
- `POST /api/v1/chat/stream` and `POST .../resume` no longer run the agent: they validate,
  record the turn as `queued`, enqueue the task and stream the turn's events back. Task
  messages carry only ids (turn, thread, user); never a key, a message text or a token.
- The worker loads the turn, its thread and its owner, decrypts the owner's OpenAI key itself
  (from `add-byok-key-isolation`), provides the operator's service keys from its environment,
  runs the turn with the existing runner, and drops the key when the turn ends.
- Events travel through a per-turn Redis Stream (`turn:{id}:events`, capped, with a TTL), so
  the browser can reattach after a reload with `GET /api/v1/chat/turns/{turn_id}/events`
  (`Last-Event-ID` = last `seq`) and miss nothing.
- New stream event `turn_status` (`queued` with queue position, `running`, `thinking`,
  `running_tool` with the step label) shown as a live status line in the chat; tool pills
  are unchanged.
- Cancellation: `POST /api/v1/chat/turns/{turn_id}/cancel` asks the worker to stop between
  graph steps; the turn becomes `interrupted` with reason `cancelled` (resumable).
- Reliability: `acks_late`, prefetch 1, a soft and a hard time limit, Redis visibility
  timeout above the hard limit, a heartbeat on the turn row; a lost worker or a stale
  heartbeat makes the turn `interrupted/worker_lost`, a soft time limit `interrupted/time_limit`
  (both resumable). Concurrency, limits, queue name and stream sizes come from `[worker]` in
  `config/settings.toml`.
- Monitoring: the trace continues across the process boundary (Logfire Celery
  instrumentation propagates the trace context in task headers); the turn span keeps the
  thread id as session id and adds the queue wait time.
- Tests run the task eagerly with an in-memory event stream; no Redis or Celery broker in
  the default `pytest` run.

## Capabilities

### New Capabilities

- `background-agent-worker`: task queue, id-only payloads, key handling in the worker, event
  stream and reattach, cancellation, time limits, lost-worker recovery, settings, test mode.

### Modified Capabilities

- `web-ui-server`: chat-turn streaming is served from the turn's event stream; adds
  `turn_status`, the reattach endpoint and the cancel endpoint; threads are no longer run in
  the API process.
- `web-ui-shell`: the copilot chat shows the live step status, a Stop control, and reattaches
  to a running turn after a reload.
- `agent-telemetry`: one trace per web turn spans the API and the worker.

## Impact

- New: `worker/__init__.py`, `worker/celery_app.py`, `worker/tasks.py`, `worker/events.py`
  (Redis Stream and in-memory bus behind one protocol), `worker/CLAUDE.md`, `config/worker.py`,
  `[worker]` in `config/settings.toml`, `tests/worker/`.
- Changed: `api/routers/v1_chat.py`, `api/services/agent_runner.py` (split "enqueue and relay"
  from "execute"), `api/schemas/chat.py` (+ contract export and `gen:types`), `compose.yaml`
  (`redis`, `worker`), `Dockerfile` (`worker` target), `app/telemetry.py` (Celery
  instrumentation), `frontend/src/hooks/useAgentStream.ts`, `chatState.ts`,
  `features/chat/ChatDock.tsx` header status and `MessageStream.tsx` status line.
- Dependencies: `celery[redis]`, `redis`; `logfire[celery]`. Dev: none new (eager mode).
- Root `CLAUDE.md`: dependency line for `worker` (see design decision 2) and the
  `worker/CLAUDE.md` entry.
- Depends on `migrate-to-postgresql`, `add-resumable-agent-turns`, `add-byok-key-isolation`.
