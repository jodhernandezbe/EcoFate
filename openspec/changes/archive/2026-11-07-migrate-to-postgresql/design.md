## Context

See proposal.md for motivation and `openspec/ROADMAP.md` ("PostgreSQL: a compose service
everywhere", "Code layout", "Configuration and secrets"). What shapes the approach:

- `ThreadStore` (`api/services/threads.py`) is synchronous and holds: the LangGraph
  `InMemorySaver` (messages), `_used` (LRU order, `max_threads` eviction), `_busy` (one turn
  per thread), `_usage` (`app.usage_meter.CallUsage`: model, input, cached input and output
  tokens), `_tool_messages` (LangChain `BaseMessage`s from which the workspace is rebuilt),
  `_workspaces` (`api.schemas.workspace.WorkspaceState`, pydantic), `_pending`
  (`tools.schemas.ConfirmationRequest`, a TypedDict), `_supplied` (key -> float) and
  `_declined` (set of keys). `messages()` reads the checkpointer's latest tuple.
- Callers: `api/services/agent_runner.py` (builds the graph with `threads.checkpointer`,
  streams with `agent.astream`, records tool messages, workspace, usage, pending),
  `api/routers/v1_chat.py` (claim/release around the SSE response, reset),
  `api/routers/v1_facilities.py` and `api/services/snapshots.py` (reads). The graph runs
  asynchronously, so the checkpointer must be the async `AsyncPostgresSaver`.
- `app/run.py` (command line) builds the agent without a checkpointer; it keeps doing so.
- Thread ids are client-generated and match `THREAD_ID_PATTERN` (`^[A-Za-z0-9_-]{1,64}$`).
- Rules: `agent/` is provider- and persistence-agnostic; settings live in `config/`; secrets
  only in the environment; setup errors raise; tests never touch real services by default.

## Goals / Non-Goals

**Goals:**
- Threads, their history and everything the dashboard rebuilds from survive restarts and can
  be served by more than one process.
- One turn per thread across processes, with no stuck thread after a crash.
- A schema ready for owners (`user_id`), turns (change 3) and the worker (change 7) without
  another redesign.
- Unit tests stay fast and offline; database behaviour is proven against real PostgreSQL.

**Non-Goals:**
- Users, ownership checks, keys, quotas (changes 4-6). `user_id` stays NULL here.
- Turn status and resume (change 3); the lease here only guarantees exclusivity.
- Amazon RDS, backups and TLS to the database (change 9; only `DATABASE_URL` changes).
- Moving the PubChem SQLite cache or the Chroma SCC index into PostgreSQL (they are
  read-through caches, rebuilt on demand, and stay in the `.cache` volume).

## Decisions

1. **SQLAlchemy 2.0 async + psycopg 3 + Alembic in a new `storage/` package.** The engine is
   created once per process (`storage.engine.create_engine(url, settings)`) and injected;
   repositories take an `async_sessionmaker`. `storage/` imports `config` and `commons`, plus
   types only from `app.usage_meter` (`CallUsage`) and `tools.schemas` (`ConfirmationRequest`)
   so the store returns the program's own types (decided during implementation; the workspace
   model still comes in as a parameter because `storage` never imports `api`); `api` imports
   `storage`; nothing in `agent/`, `tools/` or `models/` does. Alternatives:
   raw psycopg (rejected: hand-written migrations and row mapping); SQLModel (rejected: an
   extra layer over SQLAlchemy with weaker typing in strict pyright); sync SQLAlchemy in a
   thread pool (rejected: the runner is async end to end).
2. **Schema.** All tables use `thread_id text` (checked against the id pattern) and
   `ON DELETE CASCADE` from `threads`:
   - `threads(id pk, user_id uuid null, created_at, last_used_at, busy_until timestamptz null)`,
     index on `user_id` and on `last_used_at`;
   - `thread_usage(id bigserial, thread_id, seq, model, input_tokens null, cached_input_tokens,
     output_tokens null, created_at)`;
   - `thread_tool_messages(id bigserial, thread_id, seq, message jsonb)`;
   - `thread_workspaces(thread_id pk, state jsonb, updated_at)`;
   - `thread_pending(thread_id pk, request jsonb, created_at)`;
   - `thread_answers(thread_id, key, value double precision null, declined bool, pk(thread_id,
     key))` with a check that exactly one of value/declined is set.
   `user_id` is nullable now; `add-user-accounts` adds the `users` table, the foreign key and
   `NOT NULL` (deleting ownerless threads). Alternative: one `jsonb` blob per thread
   (rejected: concurrent appends of usage and tool messages would race).
3. **Codec module, fail closed on read.** `storage/codec.py` turns LangChain messages into
   JSON with `messages_to_dict` and back with `messages_from_dict`, workspaces with pydantic
   (`model_dump(mode="json")` / `model_validate`), pending requests and usage with explicit
   shape checks (finite numbers, no `bool` as a number). A row that does not decode is treated
   as absent and logged (redacted) with the thread id, never coerced. `storage/` must not
   import `api`, so the workspace codec takes the pydantic model class as a parameter.
4. **Repository contract shared by the real and the fake store.** `api/services/threads.py`
   defines `ThreadStore` as a `Protocol` of async methods with today's names and semantics
   (`claim`, `release`, `touch`, `holds`, `running`, `messages`, `add_usage`,
   `session_calls`, `add_tool_messages`, `tool_messages`, `workspace`, `set_workspace`,
   `pending`, `set_pending`, `answers`, `record_answers`, `reset`) plus `checkpointer`.
   `storage.threads.PostgresThreadStore` implements it; `tests/fakes.py` keeps an in-memory
   implementation for unit tests. One contract test module runs against both (the Postgres
   run under the `postgres` marker), so the fake cannot drift (Liskov).
5. **Lease, not a lock table.** `claim` is `INSERT ... ON CONFLICT (id) DO UPDATE SET
   busy_until = now() + lease, last_used_at = now() WHERE threads.busy_until IS NULL OR
   threads.busy_until < now() RETURNING id`; no row returned means busy (409). `release`
   sets `busy_until = NULL`. `reset` deletes the thread (cascade) and its checkpoints only when
   it is not busy. The lease is `[database].turn_lease_seconds` (default above the agent
   timeout times the step limit's practical bound; validated greater than
   `[agent].timeout_seconds`). Alternatives: PostgreSQL advisory locks (rejected: tied to a
   connection, lost on pool recycling, invisible to other processes' snapshots); Redis locks
   (rejected: Redis arrives only in change 7).
6. **Checkpointer in `app/`.** `app/checkpointer.py` exposes `open_checkpointer(url,
   settings)`, an async context manager around `AsyncPostgresSaver` on a psycopg
   `AsyncConnectionPool`, and runs its idempotent `setup()` (it owns its tables and migration
   record, separate from Alembic). The API lifespan opens it and hands it to the thread store
   and the runner. This needs only `config`, so `app` does not import `storage`
   (a deviation from the roadmap's "app -> storage (checkpointer only)": the dependency is
   not needed). Alternative: Alembic migrations for the checkpoint tables (rejected: the
   library changes its schema between versions and migrates it itself).
7. **Retention by idle time.** A lifespan task runs every `[database].purge_interval_minutes`
   and deletes threads whose `last_used_at` is older than `thread_retention_days` and that are
   not busy, together with their checkpoints (`checkpointer.adelete_thread`). `[ui].max_threads`
   and the LRU code are removed. Alternative: keep the count limit (rejected: with users it
   would let one user evict another's threads).
8. **Start-up and health.** The lifespan reads `DATABASE_URL` (variable name from
   `[database].url_env_var`); missing -> `SystemExit` with a fixed message; unreachable or the
   Alembic head not applied -> `SystemExit` naming `make migrate`. `GET /api/health` runs
   `SELECT 1` with `[database].health_timeout_seconds` and answers 503 `{"status":
   "unavailable"}` on failure (no exception text). Migrations never run implicitly in the web
   process; compose runs a one-shot `migrate` service (`python -m storage upgrade`) that `api`
   depends on with `service_completed_successfully`.
   Compose cannot publish a service's port only under a profile, so the `dev` profile adds a
   small `db-port` forwarder (`alpine/socat`, `127.0.0.1:5432` -> `db:5432`); `db` itself is
   never published.
9. **Secrets and logs.** `.env.example` gains `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `POSTGRES_DB` and `DATABASE_URL` placeholders (compose builds the URL for the services).
   `commons/key_patterns.py` adds a pattern that masks the password of
   `postgres(ql)?(+driver)?://user:password@host` URLs; SQLAlchemy is created with <!-- pragma: allowlist secret -->
   `hide_parameters=True` so bound values (answers, messages) never reach error logs.
10. **Tests.** Unit tests use the fake store and `InMemorySaver`. A `postgres` marker (excluded
    by default like `smoke`) runs the contract tests, the migration round trip (upgrade to head,
    downgrade to base, upgrade again) and the lease race (two concurrent claims, one wins)
    against `ECOFATE_TEST_DATABASE_URL`, each test in its own schema dropped afterwards;
    `make test-db` starts the `db` service and runs them. Alternative: testcontainers
    (rejected: needs the Docker socket inside pytest and adds a dependency; CI in change 8 uses
    a service container with the same variable).

## Risks / Trade-offs

- [Every store call becomes async; many call sites change] -> the Protocol keeps the names,
  and the contract tests pin behaviour before the routers are switched.
- [Lease too short: a long turn loses its lease and a second turn starts] -> validation ties
  the lease to the agent timeout; change 3 replaces it with turn rows and heartbeats.
- [Checkpoint table growth (every super-step is stored)] -> retention purge deletes whole
  threads; checkpoint pruning within a thread is out of scope.
- [Database down at run time] -> the turn ends with the generic error event and correlation
  id; health turns 503 so compose and the deploy can see it.
- [Native runs now need PostgreSQL] -> `make db` starts it alone on `127.0.0.1:5432`; the
  README states it; the command-line program does not need it.

## Migration Plan

1. Apply after `add-docker-compose-stack`. `make up` (or `make db && make migrate` for native
   runs). No data migration: in-memory threads did not survive restarts.
2. Rollback: revert the change; the `pgdata` volume can be deleted with
   `docker compose down -v`.

## Open Questions

None.
