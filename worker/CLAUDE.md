# worker/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `worker/`.

- The background worker of the web program: a thin Celery shell. `celery_app.py` builds the app
  (`app.task_queue.build_celery`, configured from `[worker]`; the Redis URL from the variable it
  names) and wires the process signals; `tasks.py` holds the one task, `ecofate.run_turn`;
  `resources.py` opens a child's services; `recovery.py` interrupts turns whose worker is gone.
  Running, recording and publishing a turn is `app.turns.job.run_background_turn`, so the API's
  in-process mode (`[worker].eager`, tests) runs exactly the same code. Never put turn logic here.
- Imports: `app`, `agent`, `config`, `storage` and `tools.credentials` only; never `api`, and
  nothing imports `worker` (`tests/test_layering.py`). Anything both the API and the worker need
  (event bus, codec, enqueuer, turn settings) lives in `app`.
- Task payload: `[turn_id, owner_id]` and nothing else, checked by `commons.payload_guard` before
  it is sent and validated again on receipt (`TurnJob.from_payload`). Never a key, a session or
  emailed token, the key-encryption key, the user's message or any tool payload: the turn's input
  is `turns.planned_input` in PostgreSQL. The trace context travels in task headers (Logfire's
  Celery instrumentation), never in arguments.
- Keys: the worker decrypts the turn owner's OpenAI key itself (`UserKeyVault.read`, once per
  turn), reads the operator's Census and CompTox keys from its environment, and the runner gives
  them to the model and tools for that turn only (`app.turns.keys.provided`, released on every
  exit). Process secrets (database and Redis URLs, KEKs, Logfire tokens) are protected from the
  logs at start-up (`app.process_secrets`); logging goes through `app.redaction`.
- Per-child resources: each prefork child opens its own event loop, engine, checkpointer pool,
  Redis client, vault and operator keys in `worker_process_init` and closes them in
  `worker_process_shutdown`; nothing is shared across the fork. Every task runs on the child's
  loop (`loop.run_until_complete`), because async pools are bound to their loop.
- Reliability: acknowledged late, prefetch from `[worker]`, never re-run when a worker is lost
  (`task_reject_on_worker_lost=False`), the hard time limit from `[worker]` (the soft one is
  enforced by the job between graph steps), Redis visibility timeout above it. The main process
  sweeps running turns with a stale heartbeat at `worker_ready` and interrupts the turn of a task
  whose child was lost or killed (`task_failure`); the user resumes, the worker never does.
- Tests (`tests/worker/`) run the task eagerly on an installed stand-in runtime and a `memory://`
  broker (no Redis, no running worker); the job itself is tested in `tests/app/turns/test_job.py`
  with `MemoryBus` and the in-memory stores. Tests against a real Redis are marked `redis`
  (`make test-redis`).
