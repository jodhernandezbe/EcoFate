# storage/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `storage/`.

- PostgreSQL for the web program: `engine.py` (the async engine and the URL), `tables.py` (the
  schema, SQLAlchemy Core), `migrations/` (Alembic), `codec.py` (rows to and from the program's
  types), `threads.py` (`PostgresThreadStore`), `turn_model.py` (`Turn`, statuses and allowed
  moves), `turns.py` (`TurnRepository`), `health.py`, `purge.py`, `revisions.py`, and
  `__main__.py` (`python -m storage upgrade | current | downgrade <rev>`).
- Imports: `config` and `commons`, plus types only from `app.usage_meter` (`CallUsage`) and
  `tools.schemas` (`ConfirmationRequest`, `MissingEntry`). Never `api` (the workspace model class
  is passed in), `agent`, tool modules or providers. `api` imports `storage`; `agent/`, `tools/`
  and `models/` never do.
- Async only (SQLAlchemy 2.0 asyncio + psycopg 3). Every statement is built with SQLAlchemy or
  bound parameters; never format a value into SQL. The engine hides bound parameters from
  errors and logs, and every statement has the `[database]` statement timeout.
- Every table has a nullable, indexed `user_id` (accounts make it required) and, except
  `threads`, a `thread_id` that cascades from `threads`, so deleting a thread deletes its rows.
- Stored rows are untrusted: decode through `codec.py` with shape and type checks (finite
  numbers, never a `bool` as a number, known message types, a valid workspace). A row that
  fails is absent and logged with its thread id (never its content); nothing is coerced.
- The schema changes only through a new Alembic revision, generated with
  `uv run alembic revision --autogenerate`, reviewed by hand (split into short helpers for the
  function-length hook), and checked with `uv run alembic check`. Never edit a revision after
  it is merged. The checkpoint tables belong to `langgraph-checkpoint-postgres` (its `setup()`),
  not to Alembic. The web program never migrates; `make migrate` does.
- The URL comes only from the environment variable named in `[database].url_env_var`; it is
  never in settings, code, images, responses or logs. Database errors are caught by name
  (`errors.DATABASE_ERRORS`) and logged by class only.
- Tests: unit tests use fakes; anything that needs PostgreSQL is marked `postgres` and runs
  in its own schema (`tests/postgres.py`) with `make test-db`.
