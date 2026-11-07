## 1. Settings and dependencies

- [ ] 1.1 Add `sqlalchemy[asyncio]`, `psycopg[binary,pool]`, `alembic` and `langgraph-checkpoint-postgres` with `uv add`; add the `postgres` marker to `[tool.pytest.ini_options]` and exclude it from the default `addopts`.
- [ ] 1.2 Add `[database]` to `config/settings.toml` (`url_env_var = "DATABASE_URL"`, `pool_size`, `pool_timeout_seconds`, `statement_timeout_seconds`, `health_timeout_seconds`, `turn_lease_seconds`, `thread_retention_days`, `purge_interval_minutes`, each commented) and `config/database.py` with a frozen `DatabaseSettings` loader; negative tests for zero/negative/boolean values, an empty variable name, and a lease not greater than `[agent].timeout_seconds`.
- [ ] 1.3 Remove `max_threads` from `[ui]` and `UiSettings` (and its validator and tests); add a test that an old file still carrying `max_threads` is rejected with a message naming `[database].thread_retention_days`.

## 2. storage/ package

- [ ] 2.1 `storage/engine.py`: `create_engine(url, settings)` (async psycopg engine, `hide_parameters=True`, pool and statement timeout from settings), `database_url(environ, settings)` that raises a setup error naming the variable when it is missing or blank; tests with a fake environment.
- [ ] 2.2 `storage/tables.py`: the six tables of the design (nullable indexed `user_id`, cascades, the id-pattern and value/declined checks). `alembic.ini` + `storage/migrations/` with the initial revision generated from them and reviewed by hand.
- [ ] 2.3 `storage/codec.py`: messages, workspace (model class as a parameter), pending request, usage and answers to and from JSON, each failing closed (returns `None` plus a logged warning) on a malformed row; negative tests for NaN, `bool` as a number, a missing field and an unknown message type.
- [ ] 2.4 `storage/threads.py`: `PostgresThreadStore` implementing the `ThreadStore` protocol (lease claim with `ON CONFLICT ... WHERE`, release, touch, reads and appends with per-thread `seq`, `reset` refusing while busy, `purge_idle(older_than)` returning the purged ids).
- [ ] 2.5 `storage/__main__.py`: `upgrade` (Alembic to head), `current` (prints the revision, exit 1 when not at head), `downgrade <rev>`; tests with a monkeypatched Alembic command.
- [ ] 2.6 `storage/CLAUDE.md`: layer rules (imports only `config`/`commons`; async only; every query parameterised; every table has `user_id`; decode failures are absent with a warning; migrations reviewed by hand, never edited after merge; the URL only from the environment). List it in the root `CLAUDE.md`.

## 3. Checkpointer and API wiring

- [ ] 3.1 `app/checkpointer.py`: `open_checkpointer(url, settings)` async context manager (`AsyncConnectionPool` + `AsyncPostgresSaver`, idempotent `setup()`); unit test with a fake pool factory.
- [ ] 3.2 `api/services/threads.py`: replace the class with the async `ThreadStore` protocol; move the in-memory implementation to `tests/fakes.py` (with `InMemorySaver`).
- [ ] 3.3 Await the store in `agent_runner.py`, `v1_chat.py` (claim/release around the SSE response; release in the background task and on every error path), `v1_facilities.py` and `snapshots.py`; `dependencies.get_threads` returns the store from `app.state`.
- [ ] 3.4 `api/main.py` lifespan: read the URL, create the engine, check the Alembic head (fail with the fixed message naming `make migrate`), open the checkpointer, build `PostgresThreadStore`, start the purge task, close everything on shutdown. Tests inject a fake store and skip the database.
- [ ] 3.5 `GET /api/health`: `SELECT 1` within `health_timeout_seconds`; 200 `ok` or 503 `unavailable` with no exception text; tests with a fake engine that raises and one that hangs.
- [ ] 3.6 `commons/key_patterns.py`: mask the password in PostgreSQL URLs (with and without a `+driver` suffix); negative tests: a URL without a password is unchanged, a password containing `@` or `:` is fully masked.

## 4. Compose and Makefile

- [ ] 4.1 `compose.yaml`: `db` (`postgres:16-alpine`, `pgdata` volume, `pg_isready` health check, `POSTGRES_*` from `.env`, port published only under the `dev` profile on `127.0.0.1:5432`), `migrate` (same image as `api`, `python -m storage upgrade`, `depends_on: db: service_healthy`), `api` gains `DATABASE_URL` and `depends_on: migrate: service_completed_successfully`.
- [ ] 4.2 `Makefile`: `migrate` runs the `migrate` service; `db` starts `db` with the `dev` profile; `test-db` runs `pytest -m postgres` with `ECOFATE_TEST_DATABASE_URL`; `psql` opens a shell in `db`. `.env.example`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL` placeholders with comments.
- [ ] 4.3 Extend `tests/test_container_files.py`: `db` is not published outside the `dev` profile and never on all interfaces; `api` waits for `migrate`.

## 5. Tests

- [ ] 5.1 `tests/api/services/test_thread_store_contract.py`: one parametrised contract suite (follow-up turn sees earlier messages; usage, tool messages, workspace, pending and answers round-trip; a supplied value is never replaced; reset clears everything and refuses while busy; claim twice -> second refused; release twice is safe), run against the fake by default and against PostgreSQL under `postgres`.
- [ ] 5.2 `tests/storage/` (`postgres` marker): migration upgrade/downgrade/upgrade round trip; two concurrent claims -> exactly one wins; an expired lease can be claimed; `purge_idle` deletes old idle threads and their checkpoints and keeps busy ones; a malformed `jsonb` row reads as absent; restart survival (a new engine and checkpointer see the thread written by the first).
- [ ] 5.3 Update the existing API tests for the async store (fake store injected); `tests/test_claude_md.py` still passes.

## 6. Documentation

- [ ] 6.1 README: PostgreSQL in the architecture (what is stored, retention, where it runs), `make db` / `make migrate` / `make test-db`, the native-run prerequisite, and the `.env` variables.
- [ ] 6.2 Root `CLAUDE.md`: `storage/` in Layout, `api -> storage` in the dependency line, `make test-db` in Commands (within the line budget). `api/CLAUDE.md`: threads live in the database through the `ThreadStore` protocol; never hold thread state on the app object.

## 7. Verification

- [ ] 7.1 `uv run pytest`, `make test-db`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, bandit, the function-length check, `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice).
- [ ] 7.2 Live check: `docker compose up --build`; `migrate` exits 0; health is ok; run a two-turn conversation; `docker compose restart api`; reload the page and the snapshot shows both turns and the workspace; a third turn sees the earlier history; `docker compose stop db` turns health to 503 and a turn ends with the generic error; the API logs show no database password.
