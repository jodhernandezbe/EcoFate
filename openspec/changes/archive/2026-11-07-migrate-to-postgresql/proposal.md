## Why

Every conversation lives in process memory (`api/services/threads.py`: a LangGraph
`InMemorySaver` plus dictionaries for usage, tool messages, workspaces, pending confirmations
and the user's answers). A restart, a deploy or a container crash loses every thread, only
one process can serve the app, and nothing can belong to a user. The rest of the roadmap
needs durable state: resumable turns (3) continue from a stored checkpoint, accounts (4) own
their threads, keys (5) and quotas (6) are rows, and the Celery worker (7) runs a turn in a
different process from the one that streams it. PostgreSQL, run as the `db` compose service
locally and on the AWS VM (see the roadmap's decision), becomes that store.

## What Changes

- A new `storage/` package (SQLAlchemy 2.0 async with psycopg 3, Alembic migrations under
  `storage/migrations/`) holding the tables and a `ThreadRepository` with the same
  operations the in-memory `ThreadStore` offers today: claim/release a turn, touch, usage,
  tool messages, workspace, pending confirmation, supplied and declined answers, reset.
  Every table carries a nullable `user_id` column (indexed) that `add-user-accounts` makes
  required.
- Turn exclusivity across processes: claiming a thread is one conditional `UPDATE` that
  takes a lease (`busy_until`), so two processes cannot run the same thread and a crashed
  process's lease expires after `[database].turn_lease_seconds`.
- The agent's message history moves to `langgraph-checkpoint-postgres`
  (`AsyncPostgresSaver`), built in `app/` from the database settings and injected into
  `agent.build_agent` as today; `agent/` stays persistence-agnostic.
- The count-based retention (`[ui].max_threads`, least-recently-used eviction) is replaced by
  time-based retention: idle threads unused for `[database].thread_retention_days` are
  deleted with their checkpoints by a periodic purge.
- A `[database]` settings table (variable name of the connection URL, pool size, timeouts,
  lease, retention, purge interval); the URL itself comes only from `DATABASE_URL`.
- The web program refuses to start without a reachable, migrated database (setup error with
  a fixed message); `GET /api/health` reports `ok` only when the database answers.
- Compose: `db` service (`postgres:16-alpine`, named volume, `pg_isready` health check, not
  published to the host except in the `dev` profile on `127.0.0.1:5432`) and a one-shot
  `migrate` service that the `api` waits for. `make migrate` runs the migrations; `make db`
  starts only the database for native runs and tests.
- Database URLs (with passwords) are added to the log redaction patterns.
- Tests: unit tests use an in-memory repository that honours the same protocol; repository
  and checkpointer contract tests run against a real PostgreSQL under a new `postgres` pytest
  marker (skipped unless `ECOFATE_TEST_DATABASE_URL` is set).

## Capabilities

### New Capabilities

- `persistent-storage`: the PostgreSQL store, migrations, repository contract, turn lease,
  retention purge, start-up and health behaviour, and test strategy.

### Modified Capabilities

- `web-ui-server`: conversation threads are durable in the database instead of process
  memory; retention is by idle time instead of a count.
- `app-configuration`: the `[database]` table; `[ui]` loses the in-memory thread maximum.

## Impact

- New: `storage/` (`__init__.py`, `engine.py`, `tables.py`, `threads.py`, `codec.py`,
  `__main__.py`, `migrations/`, `CLAUDE.md`), `app/checkpointer.py`, `config/database.py`,
  `alembic.ini`.
- Changed: `api/services/threads.py` (becomes the repository-backed store; the in-memory one
  moves to `tests/fakes.py`), `api/services/agent_runner.py`, `api/routers/v1_chat.py`,
  `api/routers/v1_facilities.py`, `api/services/snapshots.py` (await the store),
  `api/main.py` (lifespan opens the engine and checkpointer, starts the purge),
  `api/routers/v1_health.py`, `commons/key_patterns.py`, `config/ui.py`,
  `config/settings.toml`, `compose.yaml`, `Makefile`, `.env.example`, `pyproject.toml`
  (`sqlalchemy[asyncio]`, `psycopg[binary,pool]`, `alembic`, `langgraph-checkpoint-postgres`;
  marker `postgres`), root `CLAUDE.md` (layout, dependency lines, commands), `api/CLAUDE.md`,
  README.
- No change to `agent/`, `tools/`, `models/`, `evals/` or the command-line program (one-shot
  runs keep no history). Existing in-memory threads are not migrated (they never survived a
  restart).
