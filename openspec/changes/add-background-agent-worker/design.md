## Context

See proposal.md for motivation. Starting point after roadmap steps 1-5:

- `api/services/agent_runner.py::run_turn` is an async generator that loads the turn's keys,
  builds the model, runs `agent.astream(...)`, translates graph updates into contract events
  (`_translate`, `_workspace_events` via `api/services/projectors` and `state_serializer`,
  `_confirmation_events`), and always ends with `usage` and `turn_finished`.
  `api/routers/v1_chat.py` wraps it in a `StreamingResponse` (`encode_event` in
  `api/services/sse.py`), so the turn lives and dies with the request.
- `add-resumable-agent-turns` gives every turn a durable row (`queued`, `running`,
  `interrupted`, `completed`, `failed`, reason, resume count) and a resume path
  (`astream(None, config)`).
- `migrate-to-postgresql` puts history in the Postgres checkpointer and thread metadata in
  `storage/`; `add-byok-key-isolation` stores each user's OpenAI key encrypted
  (AES-256-GCM, user id as associated data, key-encryption key from
  `ECOFATE_KEY_ENCRYPTION_KEY`) and exposes a decrypt function used per turn.
- `app/telemetry.py` opens a turn span per web turn with the thread id as session id.
- The frontend reads the POST response body as SSE (`services/sse.ts::parseSseFrames`) and
  reduces events in `hooks/chatState.ts`.

## Goals / Non-Goals

**Goals:**
- Agent turns run only in a bounded worker pool; the API stays responsive and stateless
  about running turns.
- The user sees queue position and each step live, can reload and reattach, and can stop.
- No secret ever enters the broker, the event stream or a log.
- A lost or timed-out worker leaves a resumable turn, never a turn stuck `running`.
- The wire contract the browser already parses keeps working.

**Non-Goals:**
- Autoscaling, priority queues, per-user fair scheduling (the daily quota of
  `add-daily-rate-limit` is the fairness control).
- Running tools as separate tasks (a turn is one task; the graph is not split).
- Celery beat, Flower or a broker other than Redis.
- Automatic re-run of a lost turn (the user resumes; credits are theirs).

## Decisions

1. **One task per turn segment, ids only.** `ecofate.run_turn(turn_id: str)`; the turn row
   holds the thread, the owner, the kind (new/resume) and, for a new turn, the planned input
   (message text and answers note) stored in Postgres, not in the message. Alternative:
   pass the message in the task, rejected: the broker would hold user content and the
   payload rule would have exceptions.
2. **The worker never imports `api`.** `extract-turn-runner` (applied before this change)
   moved the running half of the turn into `app.turns.execute_turn`, which yields
   transport-neutral `TurnEvent`s. The worker imports only `app`, `agent`, `config`,
   `storage` and `tools.credentials`, and "nothing imports `api`" holds without exception.
   Alternative considered: let the worker import `api.services`, rejected because the two
   transports would depend on each other and the layering rule would carry a permanent
   exception.
3. **Run in the worker, present in the API.** The worker runs `execute_turn` and appends each
   `TurnEvent` to the bus, serialised (`ToolMessage`/`AIMessage` via LangChain's
   `messages_to_dict`), with a `seq`. `relay_turn(turn_id, after_seq)` in the API reads the
   bus and feeds the events through the same presenter as today (wire events, step labels,
   workspace rebuild, pending confirmation, usage summary), so the browser sees exactly the
   events it sees today. With `task_always_eager` the same code runs in-process.
4. **Redis Streams, not plain pub/sub.** `XADD turn:{id}:events MAXLEN ~ N` with the event
   JSON and `seq`; the relay uses `XREAD BLOCK` from `Last-Event-ID`. A stream keeps events
   for a late or reconnecting reader; pub/sub drops them. The stream expires
   `[worker].event_ttl_seconds` after `turn_finished`. (Deviation from the ROADMAP wording
   "Redis pub/sub"; same Redis service.)
5. **`turn_status` event, existing names kept.** The ROADMAP's dotted names (`tool.started`,
   ...) are expressed with the existing contract (`turn_started`, `tool_status`,
   `turn_interrupted`, `turn_finished`); the new `turn_status` carries `phase`
   (`queued`, `running`, `thinking`, `running_tool`), an optional `label` and, when queued,
   `position`. Renaming the vocabulary would break the frontend for no gain.
6. **Cancellation is cooperative.** The cancel endpoint sets `cancel_requested` on the turn
   row; the worker checks it after each graph update and stops the stream, marking
   `interrupted/cancelled`. A queued turn that is cancelled is marked before it starts and
   the task exits at once. No `revoke(terminate=True)`: killing a child mid-checkpoint risks
   a torn write. The hard time limit is the backstop.
7. **Reliability settings.** `task_acks_late=True`, `worker_prefetch_multiplier=1`,
   `task_reject_on_worker_lost=False` (no silent automatic re-run), `soft_time_limit` ->
   `interrupted/time_limit`, `time_limit` (hard) kills the child, broker
   `visibility_timeout` > `time_limit`. The worker writes `heartbeat_at` every
   `heartbeat_seconds`; the `task_failure` signal (worker lost) and a sweep at worker start
   and on each API read of a turn mark turns whose heartbeat is older than `stale_after_seconds`
   as `interrupted/worker_lost`. Reasons `cancelled` and `time_limit` are added to the reason
   set of `add-resumable-agent-turns`.
8. **Keys in the worker.** At task start the worker decrypts the owner's OpenAI key into a
   `SecretStr`, reads the operator keys (CompTox, Census) from its environment, enters
   `protect_secrets` and the `tools.credentials.HOLDERS` contexts for the turn, and leaves
   them when the task ends (success, interruption or exception). A missing user key marks
   the turn `failed` with the existing "add your OpenAI key" message.
9. **Process model.** Celery prefork pool, `concurrency` from settings; each task runs
   `asyncio.run(execute_turn(...))`. Database engine, checkpointer pool and Redis client are
   created per child in `worker_process_init`, never shared across fork.
10. **Tracing.** `logfire.instrument_celery()` in `app/telemetry.configure_telemetry` (both
    processes) propagates the W3C trace context in task headers (non-secret). The API opens
    the turn span and an `enqueue` span; the worker's run span is its child and carries the
    session id, queue wait seconds and the outcome. Spans pass the same scrubbing.
11. **Queue position.** The API computes it from the count of `queued` turns created before
    this one and sends it in `turn_status(queued)`; the worker sends `running` when it
    starts. An approximation, labelled "about N ahead".

## Risks / Trade-offs

- Redis outage → enqueue fails: the API answers 503 with a fixed message and the turn row is
  marked `failed` (not left `queued`).
- Event stream memory → `MAXLEN` and TTL bound it; token events are the bulk, so the cap is
  generous but finite; a reader that falls further behind than the cap reattaches from the
  snapshot.
- Two code paths for eager and real mode → identical code; eager differs only in transport,
  and one integration test (marked, opt-in) runs a real worker against compose Redis.
- Workspace projection now happens on relay, so two browser tabs on one turn each rebuild the
  workspace → rebuilding is deterministic and `ThreadStore.set_workspace` is idempotent; the
  relay of the turn's owner is the only writer of pending confirmations (keyed by turn id).

## Migration Plan

Alembic revision adds `turns.heartbeat_at`, `turns.cancel_requested`, `turns.planned_input`.
Compose gains `redis` and `worker`; `docker compose up` starts both. Rollback: revert the code
and set the API to run turns in-process (the eager path), no data migration needed.

## Open Questions

None blocking.
