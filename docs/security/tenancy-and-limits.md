[← Documentation index](../../README.md#documentation) · [Security](README.md)

# Tenancy and the daily limit

## Tenancy isolation

- Every thread belongs to the user who started it. The owner is always the signed-in user, never
  read from a body, path or query. `threads` is keyed by `(owner_id, id)`, every other thread table
  refers to it through `(owner_id, thread_id)` with `ON DELETE CASCADE`, and every repository
  method puts the owner in its `WHERE`.
- Another user's thread id answers 404 with the body of an unknown id, for reads, report, reset,
  resume, confirmation replies and facilities.
- No module-level mutable object in `api/` may hold user data; `tests/api/test_tenant_isolation.py`
  scans for it. Thread state lives in PostgreSQL, never on the app object.
- What crosses processes carries ids only (`commons/payload_guard.py` refuses a payload with a
  credential): the turn id and the owner id; the turn's input is read from PostgreSQL by the worker.

## Daily limit

Each user may start `daily_turns_per_user` new agent turns per UTC day (20 in `[limits]`;
administrators are exempt by default). Resuming a turn and answering a confirmation request are
free. Counting is one atomic statement (`storage/quota.py`); over the limit the server answers
`429` with the reset time and `Retry-After`, before anything runs. The command line and the
evaluations are not limited. Endpoint and settings: [api](../../api/docs/endpoints-and-streaming.md#daily-limit).
