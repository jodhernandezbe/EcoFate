# EcoFate roadmap: from local tool to a deployed multi-user service

EcoFate today is a single-user local app: conversation threads live in process memory
(`api/services/threads.py`, LangGraph `InMemorySaver`), API keys live in the OS keychain
(`app/key_vault.py`), the agent turn runs inside the FastAPI request, and the Monitoring view
is open to whoever reaches the page. This roadmap takes it to a containerised, multi-tenant,
bring-your-own-key (BYOK) service deployed on AWS, and reorganises the documentation for the
capstone review.

Each step is one OpenSpec change under `openspec/changes/`. Apply them in order. A change is
done when its tasks are checked, pre-commit passes, and it has been archived
(`/opsx:archive`), so the main specs always describe what is built.

## Order and dependencies

| # | Change | Depends on | Capstone criteria it serves |
|---|--------|-----------|-----------------------------|
| 1 | `add-docker-compose-stack` | none | Containerization (+1), compose up starts everything (+2), Makefile (+1), Reproducibility |
| 2 | `migrate-to-postgresql` | 1 | Reproducibility, groundwork for 3-7 |
| 2b | `extract-turn-runner` | none (apply before 3) | Code organization: one transport-neutral turn runner in `app/turns/`, so the API and the worker never import each other; no behaviour change |
| 3 | `add-resumable-agent-turns` | 2, 2b | UX: a turn stopped by exhausted credits or the step limit continues where it stopped |
| 4 | `add-user-accounts` | 2 | Multitenancy: sign up, sign in, password recovery, admin role, admin-only Monitoring |
| 5 | `add-byok-key-isolation` | 4 | BYOK: the user gives only an OpenAI key; per-user encrypted storage; no key in any log |
| 6 | `add-daily-rate-limit` | 4 | Service protection: per-user daily turn quota from configuration |
| 7 | `add-background-agent-worker` | 2, 2b, 3, 5 | UX: long turns run in a Celery worker and stream progress |
| 8 | `add-ci-pipeline` | 1 (can start any time after) | CI/CD (+2) |
| 9 | `add-cloud-deployment` | 1-8 | Deployed to the cloud (+2) |
| 10 | `reorganize-documentation` | 1-9 (README is also updated inside each change) | Problem description, Code organization, Testing, Evaluation, Monitoring, Reproducibility; peer and hiring-manager readers |

`add-ci-pipeline` is independent of 2-7; apply it early if you want CI to guard the larger
changes.

## Decisions shared by every change

These are fixed here so the changes agree with one another. A change that needs to depart
from one updates this file in the same commit.

### Runtime topology (docker compose)

| Service | Image | Role | Introduced by |
|---------|-------|------|---------------|
| `api` | built from `Dockerfile` (target `api`) | FastAPI + built React UI, SSE to the browser | 1 |
| `db` | `postgres:16-alpine` | threads, checkpoints, users, sessions, keys, quotas | 2 |
| `mailpit` | `axllent/mailpit` | catches sign-up and recovery mail in local runs (dev profile only) | 4 |
| `redis` | `redis:7-alpine` | Celery broker and result backend, progress pub/sub | 7 |
| `worker` | same image (target `worker`) | Celery worker that runs agent turns | 7 |
| `caddy` | `caddy:2-alpine` | TLS reverse proxy in production only (`compose.prod.yaml`) | 9 |

`docker compose up` starts the whole system locally; `compose.prod.yaml` overrides it for
the server, which is one EC2 instance (`t3.medium`, Lightsail lacks instance roles) deployed
through SSM Run Command, so port 22 stays closed. A one-off `migrate` container applies
Alembic migrations before `api` and `worker` start. `GET /api/health` reports liveness, and
readiness checks Postgres (and Redis once change 7 lands); compose healthchecks and the
deploy's automatic rollback use it. Data and model caches (`.cache/`, Hugging Face model) live in named volumes.

### PostgreSQL: a compose service everywhere

PostgreSQL runs as the `db` container both locally and on the AWS VM, with a named volume and
a nightly `pg_dump` to S3 in production. The application reads one `DATABASE_URL`, so moving
to Amazon RDS later is a connection-string change, not a code change. Reasons: the capstone
rewards `docker compose up` starting every dependency; one VM keeps the cost near USD 30 a
month and is easy to tear down after grading; RDS adds a VPC, security groups and about
USD 15-30 a month for no functional gain at this scale.

### Code layout

- New package `storage/`: SQLAlchemy 2.0 models, repositories and Alembic migrations
  (`storage/migrations/`), psycopg 3 driver. It imports only `config` and `commons`; its rules
  go in `storage/CLAUDE.md`.
- New package `worker/`: the Celery app and its tasks. It imports `app`, `agent`, `config`,
  `storage` and `tools.credentials`; nothing imports `worker`.
- The LangGraph checkpointer (`langgraph-checkpoint-postgres`) is built at the outer edge
  (`app/`), injected into `agent.build_agent` as today; `agent/` stays persistence-agnostic.
- Dependency lines in the root `CLAUDE.md` gain `api -> storage` and `worker -> ...`; `app`
  builds the checkpointer from `config` and `DATABASE_URL` alone, and from change 5 imports
  `storage` for the per-user key vault (`app/user_key_vault.py`, `UserKeyVault.read(user_id)`),
  used by both `api` and `worker`.
- Change 5 adds `commons/sealed_secret.py` (AES-GCM seal/open) and `commons/payload_guard.py`
  (rejects key-shaped values in queued payloads); both take everything as arguments, no I/O.
- Database access is async (SQLAlchemy async + psycopg 3, LangGraph `AsyncPostgresSaver`);
  storage contract tests run against an in-memory fake by default and real Postgres under the
  `postgres` pytest marker (`make test-db`).

### Configuration and secrets

- Non-secret values (pool sizes, timeouts, quotas, token lifetimes, Celery queue names,
  password policy) go in `config/settings.toml` under new sections `[database]`, `[auth]`,
  `[limits]`, `[worker]`, `[mail]`, each with a typed loader in `config/`, never in code.
- Secrets come only from the environment (`.env` locally, `.env.prod` on the VM filled from
  AWS SSM Parameter Store): `DATABASE_URL`, `REDIS_URL`, `ECOFATE_KEY_ENCRYPTION_KEY` (plus
  `ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS` during a `rotate-keys` run),
  `ECOFATE_SESSION_SECRET`, `SMTP_PASSWORD`, `POSTGRES_PASSWORD`, `GHCR_READ_TOKEN`
  (server only, to pull images), and the operator's service keys
  `COMPTOX_API_KEY`, `CENSUS_API_KEY`, `LOGFIRE_TOKEN`, `LOGFIRE_READ_TOKEN`. Settings name
  the variables (as `[telemetry]` does today); the values never appear in a file in git.

### Identity and tenancy

- Accounts: email + password (Argon2id via `argon2-cffi`), email verification and password
  recovery by single-use, hashed, time-limited tokens sent by email (SMTP; Mailpit locally).
- Sessions: opaque random token in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie, stored
  hashed in Postgres so it can be revoked; no JWT. The existing origin guard stays.
- Sign-up is open (`[auth].signup_open = true`, decided 2026-11-07) so reviewers can create
  accounts; verification, login throttling, the daily quota and BYOK limit abuse and cost.
- Roles: `user` and `admin`. No default admin password; the first admin is created with a
  CLI command reading the password from a prompt. Only admins see the Monitoring view and its
  endpoints.
- Every thread, checkpoint, workspace snapshot, pending confirmation, usage record and turn
  belongs to one user; every repository query filters by the authenticated user id, and an id
  that belongs to someone else answers 404 (not 403) so ids cannot be probed.

### BYOK and credentials

- The browser handles only the user's OpenAI key. CompTox, Census and Logfire keys are the
  operator's, set in the environment, and never shown, accepted or echoed by the UI or API.
- The OpenAI key is stored per user, encrypted with AES-256-GCM (`cryptography`), the user id
  as associated data, under a key-encryption key from `ECOFATE_KEY_ENCRYPTION_KEY`. Status
  endpoints say only whether a key is set. The key is decrypted per turn, inside the process
  that runs the turn, and dropped when the turn ends.
- Celery task messages carry ids only (user, thread, turn), never a key, prompt secret or
  session token; the worker loads and decrypts the key itself.
- The OS keychain (`app/key_vault.py`) remains for the local command line only.
- Every log line, span, error response and task payload passes the redaction in
  `commons/key_patterns.py`; change 2 masks `DATABASE_URL` passwords (and sets SQLAlchemy
  `hide_parameters`), change 5 adds session tokens, reset tokens and the encryption key; each
  pattern gets a negative test.

### Turns, resume and progress

- A turn is a row of the `turns` table (change 3), which replaces change 2's per-thread lease
  as the "one turn per thread" guard. Status: `queued`, `running`, `interrupted`,
  `completed`, `failed`. An interruption records a reason (`out_of_credits`, `rate_limited`,
  `bad_key`, `step_limit`, `provider_down`, `worker_lost`, `time_limit`, `cancelled`) that
  the UI turns into a fixed message; an interrupted turn abandoned by a new message becomes
  `failed` with reason `superseded`. Unexpected errors are `failed`, not resumable.
- Resume continues the same LangGraph thread from its last checkpoint (`invoke(None, ...)`),
  never re-sending the user message and never re-running completed tool calls; a step-limit
  resume gets a fresh step budget, at most `[agent].max_resumes_per_turn` times. A lost worker
  never re-runs a turn by itself: the user's credits are spent only when the user resumes.
- Progress events keep the existing names (`turn_started`, `tool_status`, `turn_finished`)
  plus `turn_interrupted` and `turn_status`, one schema in `api/schemas/`, delivered over the
  existing SSE stream; with the worker they travel through Redis Streams (not pub/sub) so a
  reloaded page reattaches with `Last-Event-ID` without losing events.
- Run in the core, present at the edge (change 2b): `app.turns.execute_turn` runs a turn and
  yields transport-neutral `TurnEvent`s with failure reason codes; the web layer turns them
  into wire events, step labels, workspace updates and fixed messages. The worker runs
  `execute_turn` and publishes its events; the API relays them through the same presenter.
  "Nothing imports `api`" holds without exception, enforced by `tests/test_layering.py`.
  Log redaction lives in `app/redaction.py` so both processes share it.

### Rate limit

- One per-user daily quota of agent turns (resumes count as zero), reset at 00:00 UTC, from
  `[limits].daily_turns_per_user` in `config/settings.toml`; `[limits].admin_exempt` decides
  whether admins are counted. Counted atomically in Postgres. Over the quota the API answers
  429 with the reset time and the UI says so before the user types.

## Backlog (not proposed yet)

Capstone points still open after these changes; each would be a change of its own:

- **Retrieval evaluation** (Knowledge base, 1 -> 2): the SCC semantic search
  (`tools/emissions/rag/`) has no retrieval metrics. A hand-labelled NAICS -> SCC set with
  hit-rate and MRR for embedding vs. keyword vs. hybrid search, the best one kept, documented.
- **User feedback** (Monitoring bonus +1): thumbs up/down with an optional comment on each
  answer, stored per user in Postgres and shown in the admin Monitoring view.
- **Logs to ground truth** (Monitoring bonus +2): a command that turns recorded sessions
  (and their feedback) into rows of `evals/catalogue/scenarios.csv` for the catalogue run.
- **Evaluation used for tuning** (Evaluation 2 -> 3): document the judge-prompt iterations
  and a model comparison (e.g. gpt-4.1 vs. a cheaper model) as tuning decisions with numbers.
