## 1. Settings and dependencies

- [ ] 1.1 `uv add "celery[redis]" redis "logfire[celery]"`; add `[worker]` to `config/settings.toml` (queue, concurrency, prefetch 1, soft and hard time limit, visibility timeout, heartbeat and stale-after seconds, event stream max length and TTL, eager flag, `redis_url_env_var = "REDIS_URL"`) with comments, and a typed loader `config/worker.py` validating positive numbers, `visibility_timeout > time_limit > soft_time_limit`; negative tests (wrong order, zero, `bool`).
- [ ] 1.2 Alembic revision: `turns.heartbeat_at`, `turns.cancel_requested`, `turns.planned_input`; add `cancelled` and `time_limit` to the interruption reasons; repository tests.

## 2. Worker package

- [ ] 2.1 `worker/celery_app.py`: Celery app from `[worker]` and `REDIS_URL` (`task_acks_late`, `worker_prefetch_multiplier`, `task_reject_on_worker_lost=False`, limits, `visibility_timeout`), per-child resources in `worker_process_init`, `task_always_eager` from the setting.
- [ ] 2.2 `worker/events.py`: `TurnEventBus` protocol with `RedisStreamBus` (`XADD` with `MAXLEN`, `XREAD BLOCK` from a `seq`, expiry after `turn_finished`) and `MemoryBus` for tests; tests for ordering, resume from `Last-Event-ID`, and expiry.
- [ ] 2.3 `worker/tasks.py`: `run_turn(turn_id)` loads the turn, decrypts the owner's key, provides operator keys, runs `execute_turn`, heartbeats, checks `cancel_requested` after each update, maps soft time limit and lost worker to interruptions; the `task_failure` signal and a start-up sweep mark stale turns `worker_lost`.
- [ ] 2.4 Tests (eager, `MemoryBus`, fake model, fake vault): a turn publishes the same event sequence as today; the task message contains only the turn id (assert on the serialized message: no key, no message text, no session token); key holders are empty after success, interruption and exception; cancel mid-turn -> `interrupted/cancelled`; soft time limit -> `interrupted/time_limit`; stale heartbeat -> `worker_lost`; missing key -> `failed` with the fixed message.
- [ ] 2.5 Import boundary test (extend `tests/test_layering.py` from `extract-turn-runner`): `worker` imports only `app`, `agent`, `config`, `storage`, `tools.credentials`; nothing imports `api`; nothing imports `worker`.

## 3. API

- [ ] 3.1 Add `relay_turn` to `api/services/agent_runner.py`: read serialised `TurnEvent`s from the bus from a `seq`, deserialise, and pass them through the existing presenter (the worker runs `app.turns.execute_turn`); round-trip tests for every `TurnEvent` type; keep each function within 18 lines.
- [ ] 3.2 `/chat/stream` and `/threads/{id}/resume`: record `queued` + planned input, enqueue, emit `turn_status(queued, position)`, relay. Redis down -> 503 fixed message and the turn `failed`; test.
- [ ] 3.3 `GET /api/v1/chat/turns/{turn_id}/events` (reattach with `Last-Event-ID`) and `POST /api/v1/chat/turns/{turn_id}/cancel`; negative tests: unknown turn 404, finished turn cancel 409, malformed id 422, another user's turn 404 (with `add-user-accounts`).
- [ ] 3.4 Add `turn_status` to `api/schemas/chat.py`; the snapshot reports a running turn's id so the UI can reattach; export the contract and `gen:types`.

## 4. Monitoring

- [ ] 4.1 `logfire.instrument_celery()` in `app/telemetry.configure_telemetry`; the worker span is a child of the API turn span with session id and queue wait seconds; test with an in-memory exporter that both spans share a trace id and that no span attribute matches the key patterns.

## 5. Containers

- [ ] 5.1 `Dockerfile` `worker` target (`celery -A worker.celery_app worker`), `compose.yaml` services `redis` (healthcheck, no published port) and `worker` (depends on `db` and `redis` healthy, shares the model cache volume); `docker compose up` starts the whole system.

## 6. Frontend

- [ ] 6.1 `chatState.ts`: handle `turn_status` (status line text: "Waiting for a worker (about N ahead)", "Thinking", "Running: <label>"); reducer tests.
- [ ] 6.2 `useAgentStream.ts`: reattach on load when the snapshot reports a running turn, resume reading from the last `seq` after a dropped connection, `stop()` calling the cancel endpoint.
- [ ] 6.3 `ChatDock.tsx` header status adds queued; `MessageStream.tsx` shows the status line under the streaming message and a **Stop** control while a turn runs; component tests; `/ui-check` light and dark.

## 7. Documentation

- [ ] 7.1 New `worker/CLAUDE.md` (task payload rule, key handling, per-child resources, eager tests, import boundary), list it in the root `CLAUDE.md` and update the dependency line (stay within the line budget), `api/CLAUDE.md` (endpoints enqueue and relay; no agent runs in the API), README (architecture diagram with `redis` and `worker`, what the user sees while a turn runs, how to watch the worker logs), and confirm `openspec/ROADMAP.md` still matches (Redis Streams, worker import boundary).

## 8. Verification

- [ ] 8.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, `uv run bandit -c pyproject.toml -r agent app api commons config evals models prompts tools storage worker`, the function-length check (add `worker/*.py`), `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice).
- [ ] 8.2 One live check with `docker compose up`: run an assessment, reload the page mid-turn and confirm it reattaches without missing pills; press Stop and then Resume; `docker compose kill worker` mid-turn and confirm the turn becomes `worker_lost` and resumes after `docker compose start worker`; inspect `redis-cli XRANGE` and the worker log for any key or token (none expected); confirm one Logfire trace spans API and worker.
