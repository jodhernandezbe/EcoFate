[← Documentation index](../README.md#documentation) · [Architecture](../docs/architecture.md) · [Security](../docs/security/README.md)

# storage/

PostgreSQL for the web program: the async engine, the schema, the Alembic migrations and the
repositories. The web program keeps every conversation here, so a thread survives a restart and
any process connected to the same database can serve its next turn. Rules for coding agents:
`storage/CLAUDE.md`.

## Contents

- [Conversation storage](#conversation-storage)
- [Tables](#tables)
- [Migrations](#migrations)
- [Checkpoints](#checkpoints)
- [Running and testing](#running-and-testing)

## Conversation storage

- **What is stored:** the message history (LangGraph checkpoints, in tables the checkpoint library manages), the session's token usage, the tool calls and results the dashboard is rebuilt from, the latest workspace, an open confirmation request, and the values the user supplied or declined. Every thread belongs to the user who started it: its rows carry the owner's id, the thread is identified by owner and thread id together (two users may pick the same id), and every query filters by the signed-in user.
- **One turn at a time:** a turn claims its thread with a lease (`[database].turn_lease_seconds`); a second turn on the same thread is answered 409, and a crashed process's lease expires.
- **Turn status:** every turn has a row in `turns` (`queued`, `running`, `interrupted`, `completed` or `failed`, with its reason, resume count, times, the worker's heartbeat, a cancel request and, for a new turn, its input); at most one turn per thread is open (a partial unique index). A running turn whose worker's heartbeat stops for `[worker].stale_after_seconds` becomes `interrupted` (`worker_lost`) so it can be resumed; nothing is re-run without the user.
- **Retention:** threads idle for `[database].thread_retention_days` are deleted with their history by a purge that runs every `[database].purge_interval_minutes`; a running thread is never purged.
- **Where it runs:** the `db` compose service, locally and on the server. The schema changes only through Alembic migrations (`make migrate`); the web program never migrates by itself. Settings live in `[database]` in `config/settings.toml`; the URL, which carries the password, only in the environment.

## Tables

Defined in `tables.py` (SQLAlchemy Core); rows are decoded through `codec.py`, which checks shape
and type and treats a bad row as absent.

| Table | Holds |
|---|---|
| `users`, `sessions`, `auth_tokens`, `login_attempts` | accounts; a session or emailed token only as its hash; attempts for the throttle |
| `user_credentials` | a user's sealed OpenAI key: nonce, ciphertext and the id of the key-encryption key (never a plaintext) |
| `threads` | one per `(owner_id, id)` |
| `turns` | status, reason, resume count, heartbeat, cancel request, planned input |
| `thread_usage`, `thread_tool_messages`, `thread_workspaces`, `thread_pending`, `thread_answers` | usage, tool messages, workspace, open confirmation request, the user's answers; each refers to `threads` by `(owner_id, thread_id)` with `ON DELETE CASCADE` |
| `daily_turn_usage` | turns started per user per UTC day (the daily limit) |

Repository modules: `threads.py` (`PostgresThreadStore`), `turns.py` (`TurnRepository`),
`users.py`, `user_sessions.py`, `auth_tokens.py`, `login_attempts.py`,
`user_credentials.py` (`CredentialRepository`), `quota.py` (`QuotaRepository`), `purge.py`,
`health.py`. Every repository method takes a `ThreadKey` (or the owner id) and puts the owner in its
`WHERE`; the few calls across users (retention purge, recovery sweeps, queue position, one user's
account deletion, key rotation) are named in `storage/CLAUDE.md`.

## Migrations

Alembic revisions are in `migrations/versions/` (`0001_create_thread_tables` to
`0006_add_turn_worker_columns` at the time of writing). The schema changes only through a new
revision:

    uv run alembic revision --autogenerate -m "<what changes>"   # then review it by hand
    uv run alembic check
    make migrate                                                  # apply (or: uv run python -m storage upgrade)
    uv run python -m storage current                              # the current revision

`python -m storage` also has `downgrade <rev>`. A merged revision is never edited. In Docker the
one-shot `migrate` service applies the migrations before `api` and `worker` start.

## Checkpoints

The conversation history is kept by `langgraph-checkpoint-postgres`, whose tables belong to its own
`setup()` and not to Alembic. One process sets them up at a time (`[database].setup_lock_*_seconds`),
because the API and every worker start together on a fresh database. The checkpointer's thread key
is `ThreadKey.checkpoint_id` (`"{owner}:{thread}"`).

## Running and testing

Unit tests use fakes (`tests/fakes.py`). Anything that needs PostgreSQL is marked `postgres` and
runs in its own schema:

    make test-db       # starts the db service and runs pytest -m postgres
    make psql          # a psql shell in the db service
