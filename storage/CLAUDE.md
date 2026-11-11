# storage/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `storage/`.

- PostgreSQL for the web program: `engine.py` (the async engine and the URL), `tables.py` (the
  schema, SQLAlchemy Core), `migrations/` (Alembic), `codec.py` (rows to and from the program's
  types), `threads.py` (`PostgresThreadStore`), `turn_model.py` (`Turn`, statuses and allowed
  moves), `turns.py` (`TurnRepository`), `keys.py` (`ThreadKey`), the accounts (`account_model.py`,
  `users.py`, `user_sessions.py`, `auth_tokens.py`, `login_attempts.py`), `user_credentials.py`
  (`CredentialRepository`: a user's sealed secrets), `health.py`, `purge.py`,
  `quota.py` (`QuotaRepository`, the daily turn quota), `revisions.py`, and `__main__.py` (`python -m storage upgrade | current | downgrade <rev>`).
- Imports: `config` and `commons`, plus types only from `app.usage_meter` (`CallUsage`) and
  `tools.schemas` (`ConfirmationRequest`, `MissingEntry`). Never `api` (the workspace model class
  is passed in), `agent`, tool modules or providers. `api` imports `storage`; `agent/`, `tools/`
  and `models/` never do.
- Async only (SQLAlchemy 2.0 asyncio + psycopg 3). Every statement is built with SQLAlchemy or
  bound parameters; never format a value into SQL. The engine hides bound parameters from
  errors and logs, and every statement has the `[database]` statement timeout.
- Every conversation artefact belongs to one user. `threads` is keyed by `(owner_id, id)` (two
  users may pick the same thread id) and every other thread table refers to it through the
  composite key `(owner_id, thread_id)` with `ON DELETE CASCADE` (`turns` names its owner column
  `user_id`), so deleting a thread or its user deletes its rows. Every repository method on these
  tables takes a `ThreadKey` (or the owner id with a turn id) and puts the owner in its `WHERE`;
  none exists without one. The only calls across users are `purge_idle` (retention),
  `TurnRepository.interrupt_all_open` and `interrupt_stale` (recovery), `queue_position` (a
  count only) and `forget_owner` (one user's account deletion); `release_lease` is the lease
  release a worker's recovery uses without a checkpointer. The checkpointer's thread key is
  `ThreadKey.checkpoint_id` (`"{owner}:{thread}"`).
- Turns: a new turn is `queued` with its `planned_input` (JSONB, read by the worker; task
  messages carry ids only), `start` moves it to `running` once (a second delivery does nothing),
  the worker renews `heartbeat_at` and the thread's lease (`extend`), `cancel_requested` asks it
  to stop, and a resume queues it again.
- Daily quota: `daily_turn_usage(user_id, day, turns)`; counting is one atomic upsert guarded by
  `WHERE turns < limit`, the day is the database's UTC date, a refund is guarded by
  `turns.quota_refunded`, and old rows go in the idle-retention purge.
- `user_credentials` holds only nonce, ciphertext and the id of the key-encryption key that sealed
  it (never a plaintext or a key); it cascades with the user. Every method takes `user_id` except
  the rotation batch (`unsealed_by_other_keys`, `count_sealed_by`), the one cross-user call.
- Accounts: `users`, `sessions`, `auth_tokens`, `login_attempts`. A session or emailed token is
  stored only as its hash (the repository is given the hash, never the token). Using a token or
  counting a failed attempt is one atomic statement.
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
