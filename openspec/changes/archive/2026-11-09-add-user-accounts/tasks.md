## 1. Settings and storage

- [x] 1.1 Add `[auth]` (signup_open, password min/max length, session idle and absolute lifetimes, verification and reset token lifetimes, cookie name, cookie_secure, trusted_proxy_hops, session_secret_env_var), `[auth.argon2]`, `[auth.throttle]` (attempts, window) and `[mail]` (host, port, starttls, from address, username, password_env_var, app base URL, timeout) to `config/settings.toml` with comments; typed loaders `config/auth.py` and `config/mail.py`; negative tests (non-positive lifetimes, min > max, `cookie_secure = false` with environment `production`).
- [x] 1.2 Add `user_id` to `[telemetry.attributes]` and its loader field.
- [x] 1.3 In `storage/`: models and repositories for `users` (UUID id, normalised email unique, password hash, role, verified_at, created_at), `sessions` (token hash, user, created, last seen, idle/absolute expiry), `auth_tokens` (purpose, user, token hash, expires, used), `login_attempts` (key, window start, count); add non-null `owner_id` to every thread table and non-null `user_id` to `turns`, make `(owner_id, thread_id)` the key (including the one-active-turn constraint); every async repository method on threads, turns, workspaces, pending confirmations, supplied/declined values and usage takes `owner_id`; extend the shared `ThreadStore` contract tests so the Postgres and fake stores both pass the crosswise cases.
- [x] 1.4 Alembic migration (up deletes pre-accounts threads; down drops the new tables/column); test up/down against the compose Postgres.

## 2. Auth services

- [x] 2.1 `api/services/auth/passwords.py`: Argon2id hash/verify/needs-rehash with configured parameters, dummy-hash verification for unknown emails, password policy.
- [x] 2.2 `api/services/auth/tokens.py`: random token, SHA-256 hash, issue (invalidating older tokens of the purpose), atomic consume (`UPDATE ... RETURNING`).
- [x] 2.3 `api/services/auth/sessions.py`: create (rotating any presented cookie), resolve (idle/absolute expiry, touch), revoke one/all.
- [x] 2.4 `api/services/auth/throttle.py`: per-email and per-IP counters, client address with trusted proxy hops.
- [x] 2.5 `api/services/auth/mailer.py`: SMTP client with timeout, sent from a background task, links built from `[mail].app_base_url` with the token in the fragment; a fake mailer for tests.

## 3. API

- [x] 3.1 `api/core/session_guard.py`: `current_user` and `require_admin` dependencies (401 / 404), generic bodies with correlation id.
- [x] 3.2 `api/routers/v1_auth.py` (signup, verify, resend, signin, signout, forgot, reset, me) and `api/routers/v1_account.py` (change password, sign out everywhere, delete account); wire schemas in `api/schemas/auth.py`; regenerate the contract (`uv run python -m scripts.export_contract`, `npm --prefix frontend run gen:types`).
- [x] 3.3 Add `Depends(current_user)` to chat, facilities, settings (except client config) routes; `require_admin` on monitoring.
- [x] 3.4 `ThreadStore` Protocol methods take `ThreadKey(owner_id, thread_id)`; resume and turn-status routes from step 3 look up `turns` by owner; checkpointer thread key `"{owner_id}:{thread_id}"`; snapshot, report, reset and stream look up by owner and answer 404 on a miss.
- [x] 3.5 Monitoring: owner column resolved from `users` by the span's user id; `app/telemetry.py` `session_span` takes an optional `user_id`.
- [x] 3.6 `api/__main__.py create-admin --email [--password-stdin]` with `getpass`, refusing a non-TTY without the flag.

## 4. Frontend

- [x] 4.1 Read `frontend/DESIGN.md` and use the `ui-craft` skill; add `features/auth/` (sign in, sign up, check email, verify, forgot, reset) with loading, error and success states, fragment token handling and no storage.
- [x] 4.2 `services/apiClient.ts`: 401 → signed-out state that unmounts the workspace; `hooks/useSession.ts` for `me`.
- [x] 4.3 `LeftNavRail`: Account entry (email, sign out, change password, delete account dialog), Monitoring only for admins; `App.tsx` switches between account screens and workspace. Do not change the Overview, Map or Chat panels.
- [x] 4.4 Vitest tests for each screen state, 401 handling, rail entries per role, no-storage check; `/ui-check` in light and dark.

## 5. Tests (one negative test per rule)

- [x] 5.1 Sign-up enumeration: same status/body for new and existing email; existing password unchanged.
- [x] 5.2 Sign-in: wrong password vs unknown email identical; unknown email still verifies a dummy hash (spy); unverified state; cookie flags; stored value is a hash; a stored hash is not accepted as a cookie; session fixation (pre-existing cookie replaced).
- [x] 5.3 Tokens: expired, reused, superseded, concurrent double-consume (two transactions) succeeds once; reset revokes all sessions.
- [x] 5.4 Throttling: email and IP limits, `Retry-After`, password not checked when limited, forged `X-Forwarded-For` ignored without trusted proxy.
- [x] 5.5 Authorization: every route without a session → 401 (parametrised over the app's route table, minus the public allow-list); non-admin monitoring → 404 with no Logfire call.
- [x] 5.6 Tenant isolation: two users, every thread route crosswise → 404 identical to unknown; same thread id for both users stays separate; concurrent turns on the same id both run; release by another user does not free the thread; module-level mutable state scan of `api/`.
- [x] 5.7 Secrets: password, session, verification and reset tokens absent from logs (debug level), responses, spans and access log lines.
- [x] 5.8 `create-admin`: password never in argv/output; non-TTY refusal; promote keeps the password.

## 6. Compose and documentation

- [x] 6.1 Add the `mailpit` service (profile `dev`) to `compose.yaml` and `[mail]` defaults pointing at it; document `ECOFATE_SESSION_SECRET` and `SMTP_PASSWORD` in `.env.example`.
- [x] 6.2 README: accounts, first admin (`create-admin`), Mailpit inbox URL, admin-only Monitoring; `api/CLAUDE.md` (auth layering, ownership rule, 404 policy), root `CLAUDE.md` dependency line if `api -> storage` changes; update `openspec/ROADMAP.md` only if a shared decision changed.

## 7. Verification

- [x] 7.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, `uv run bandit -c pyproject.toml -r agent app api commons config evals models prompts tools`, function-length check, `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice).
- [x] 7.2 Run `/security-audit` on the change and resolve every confirmed finding.
- [x] 7.3 Live check with `docker compose --profile dev up`: sign up, open the Mailpit link, verify, sign in, run one turn, sign in as a second user and confirm the first user's thread id answers 404, recover a password, and confirm a non-admin gets 404 from `/api/v1/monitoring/sessions` while the admin sees both users' sessions.
