# api/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `api/`.

- A thin HTTP/SSE transport, security and state-serialisation adapter over the agent core.
  Never duplicate physics, EPA queries or read-across math here; those live in `tools/` and
  `models/`. If the UI needs a new fact, it needs a tool, not an `api/` function.
- Layering: `routers/` (thin handlers, no logic) -> `services/` (orchestration: agent runner,
  state serializer, threads, usage) -> the agent core. `core/` holds config view,
  the uvicorn log config (the filter itself is `app.redaction`) and exception handlers;
  `schemas/` holds every wire model.
- `services/agent_runner.py` presents a turn and never runs the graph itself: it calls
  `app.turns.execute_turn` and turns each `TurnEvent` into wire events (sequence numbers, step
  labels, workspace rebuild, pending confirmation, usage summary) and does the `ThreadStore`
  bookkeeping. `services/provider_errors.py` maps a `FailureReason` to its fixed message.
- Allowed imports: `app`, `agent`, `config`, `commons`, `prompts`, `storage`, `tools.schemas` (types
  only) and `tools.user_values` (checks an entered value). Never import tool modules, provider packages or `evals`; nothing imports `api`.
- Settings come from `[ui]` in `config/settings.toml` via `config.ui`; `api/core/config.py`
  only exposes them to `Depends()`. Never read ports, origins or names from the environment.
  The container bind address comes only from `[ui.container]`, used when `python -m api
  --container` runs; the origin checks always use `[ui].host:[ui].port`, whatever is bound.
  `GET /api/health` (container health checks) answers `ok` only when the database answers
  `SELECT 1` within `[database].health_timeout_seconds`, else 503 `unavailable`; it reads no
  key and runs no agent.
- Accounts (`services/auth/`, `routers/v1_auth.py`, `v1_account.py`, `core/session_guard.py`):
  layered as stores (`stores.py` protocols; `storage/` in production, `tests/fakes_accounts.py` in
  tests) -> one module per concern (`passwords` Argon2id, `tokens` keyed hashes and single-use
  tokens, `sessions`, `throttle`, `mailer`/`messages`) -> `flows.AuthService` -> thin routers. Every
  route needs `Depends(current_user)` (401, generic) except health, the static UI, the client
  display settings and the public auth routes; Monitoring needs `require_admin` (404 like an unknown
  route). Answers are fixed messages: sign-up, resend and forgot answer alike for any email, a failed
  sign-in is one message, and an unknown email still pays for one password verification. Emails are
  returned by the flows and sent after the response (`mailer.deliver`, which logs only the exception
  class); links carry the token in the URL fragment and no route takes a token in a query string. The
  session secret comes from the environment variable named in `[auth]` (the app refuses to start
  without it), and so does the SMTP server (`services/auth/smtp.py` reads the `SMTP_*` variables
  `[mail]` names, checks each and names a bad one; in container mode a loopback host is Mailpit) and only the keyed hash of a session or token is stored. Passwords are `SecretStr`.
- Ownership: the owner is always `current_user.id`, never read from a body, path or query.
  Routers build `ThreadKey(user.id, thread_id)` and pass it to every `ThreadStore` call; a thread of
  another user is simply not found (404 with the body of an unknown id, for reads, report, reset,
  resume, confirmation replies and facilities). The checkpointer key is `ThreadKey.checkpoint_id`.
  No module-level mutable object may hold user data (`tests/api/test_tenant_isolation.py` scans
  `api/`; a new reviewed constant table goes in its allow-list). `python -m api create-admin` is the
  only way to make an admin (hidden prompt or `--password-stdin`, never an argument).
- Threads (history, usage, tool messages, workspace, pending request, answers) live in
  PostgreSQL behind the `services/threads.ThreadStore` protocol (`storage.threads` in
  production, `tests/fakes.InMemoryThreadStore` in tests). Never hold thread state on the app
  object or in module globals: another process may serve the next turn. Every store call is
  awaited; a turn claims its thread (409 when busy) and releases it on every path.
  `services/database.py` opens the database in the lifespan and refuses to start without a
  migrated one; tests pass `create_app(..., threads=InMemoryThreadStore(), accounts=...)` (see `tests/api/auth_support.build_app`) and never touch it.
- Turn status (`services/turn_lifecycle.py`, store `ThreadStore.turns`): each turn has a record;
  with the lease held, a turn left open is stale (`interrupted/worker_lost`), and a new message
  marks an interrupted latest turn `failed/superseded` (the runner closes its unanswered tool
  calls). A `FailureReason` that `app.turns.resumable` accepts interrupts the turn
  (`turn_interrupted`); any other fails it (`error`). `POST .../resume` continues only the
  latest interrupted turn, under `[agent].max_resumes_per_turn`, with a key and a next step
  (none: mark it completed); every refusal is 409 with a fixed message and changes nothing. A
  stream the client leaves interrupts its turn (`worker_lost`); start-up does the same.
- Daily quota (`services/quota.py`, `routers/v1_usage.py`, `[limits]` via `config.limits`): the chat
  router counts a new message (`QuotaService.require`, 429 with `Retry-After`) after the thread claim
  and before `plan_turn`, so nothing runs and no model is built over the limit. Resume and an answer
  to the open confirmation request never count. The runner gives a counted turn back (`refund`) only
  when it stops for a reason that cannot be resumed and made no model call; counting itself is one
  atomic statement in `storage/quota.py`, never a read then a write.
- The chat model is built only through `app.chat_model`. Keys are bring-your-own: the user's OpenAI
  key lives in `user_credentials`, sealed (AES-256-GCM, owner and purpose as associated data) under
  the key-encryption key, and `app.user_key_vault.UserKeyVault` is the only module that decrypts it:
  `read(user_id)` once per turn through `services/key_setup.turn_key_loader` (passed to the runner as
  its key loader), given to the model and tools for that turn only, protected from the logs and never
  stored on anything that outlives the turn; never in `os.environ`. A user with no usable key ends
  with the add-your-key message whatever the operator keys. Only `/api/v1/settings/openai-key` (and
  `/keys`, with the data services' availability) touch keys; there are no Census or CompTox routes,
  and no response, event or error carries any part of a key.
- Operator keys (Census, CompTox, the key-encryption keys, Logfire tokens, session secret, SMTP
  password) are read from the environment at start-up by `services/key_setup.py`
  (`app.operator_keys`), registered with `app.redaction.protect_for_process` and handed to the tools
  per turn like the user's key. A missing or malformed key-encryption key stops the program with a
  message naming the variable. `python -m api rotate-keys` re-seals every stored key (counts only).
  Anything handed to another process carries ids only, checked by `commons.payload_guard`.
- `api/schemas/` is the single wire contract with `frontend/`. After changing it run
  `uv run python -m scripts.export_contract` and `npm --prefix frontend run gen:types`.
- Responses, events and logs never contain exception text, request headers or key material;
  log through the redaction filter and return a generic message with a correlation id.
- The workspace shows only what tools returned: never compute, estimate or convert values
  (geometry for drawing the buffer and schematic sector is the one exception); anything
  unverified or unattributable becomes absent with a reason.
- `services/exposure_graph/` turns each validated `Facility` into its `exposure_graph` (source, one
  lane per pathway, nodes and edges with value, unit and source or a reason). It only rearranges
  values; a lane is one module in `LANES`; its fixed text and units are `[ui.exposure_graph]`.
- `services/report/` writes a thread's Word report (one module per section) from its
  `WorkspaceState` and last assistant message only: it formats values (`values.py`, the same text
  as the dashboard) and never computes one; its fixed text is `[ui.report]`.
- `services/monitoring/` reads recorded sessions back from the Logfire query API for the
  Monitoring view (`client.py` the only module that talks to it, `queries.py` the SQL, `rows.py`
  the untrusted-row parsers, `sessions.py` and `timeline.py` the figures, `service.py` the states).
  The read token comes from the environment variable named in `[telemetry]`, never from the
  user or the keychain; it is used only there, protected from the logs, and never returned or
  given to the agent. Statements take values only as quoted literals (ids match
  `THREAD_ID_PATTERN`). Everything shown comes from the spans; a missing figure is absent, and
  Logfire failures are a state with a user-safe message, never invented sessions.
- Tests mirror the layout under `tests/api/`; they inject `tests.fakes.KeyBench` (a real
  `UserKeyVault` over an in-memory store), a fake chat model and never touch a real provider.
