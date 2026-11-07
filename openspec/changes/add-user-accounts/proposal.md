## Why

EcoFate is a single-user local app: anyone who reaches the page can chat, read every thread
the process holds (thread ids are chosen by the browser and never checked against a person),
and open the Monitoring view, which shows every recorded question and tool call. Deploying it
(roadmap step 9) needs people to have accounts, each person's work to be invisible to
everyone else, and the Monitoring view, which exposes everyone's questions, to be reserved for
the operator. This is roadmap step 4 and the base of BYOK (step 5) and the daily quota
(step 6).

## What Changes

- **Accounts**: sign up with email and password, email verification, sign in, sign out, and
  password recovery by email. Passwords are hashed with Argon2id; verification and recovery
  tokens are random, single-use, stored only as hashes and expire after a configured time.
  Responses and their timing never reveal whether an email has an account.
- **Sessions**: an opaque random session token in an `HttpOnly`, `Secure`, `SameSite=Lax`
  cookie, stored hashed in Postgres with idle and absolute expiry, revoked on sign out and on
  password change or reset. No JWT. The existing origin guard stays in front of every route.
- **Login throttling**: failed sign-in and recovery attempts are limited per account and per
  client address within a window from configuration; over the limit the API answers 429
  without saying whether the password was right.
- **Roles**: `user` and `admin`. No default admin and no default password; the first admin is
  created (or an account promoted) with `uv run python -m api create-admin`, which reads the
  password from a hidden prompt.
- **Admin-only Monitoring**: the Monitoring endpoints answer 404 to non-admins and the rail
  hides the entry. Spans carry an opaque user id (never an email) so the admin view can show
  whose session it was, resolved to an email from Postgres, never from Logfire.
- **Tenant isolation**: every thread, turn record (the `turns` table of step 3), checkpoint,
  workspace, pending confirmation, supplied or declined value, usage record and report
  belongs to one user. Every lookup filters by the
  signed-in user; another user's id answers 404, exactly like an id that does not exist. The
  in-memory per-turn state (busy set, live workspaces, pending confirmations) is keyed by
  owner and thread, so concurrent turns of different users cannot see or release each other.
- **Account management**: change password, sign out everywhere, delete account (deletes the
  user's threads, sessions and, after step 5, their stored key).
- **Frontend**: sign-in, sign-up, verify-email, forgot-password and reset-password screens
  before the workspace, and an account entry in the rail (email, sign out). The existing
  dashboard panels (Overview, Map, Chat) do not change.
- **Mail**: SMTP settings in `[mail]`; local runs send to the `mailpit` compose service
  (dev profile), whose web inbox shows the links.

## Capabilities

### New Capabilities

- `user-accounts`: sign up, verification, sign in and out, sessions, password recovery,
  throttling, roles, the create-admin command, account management.
- `tenant-isolation`: per-user ownership of every stored and in-memory artefact of a
  conversation, 404 on foreign ids, isolation of concurrent turns.

### Modified Capabilities

- `web-ui-server`: every route except health, the static UI and the public auth routes needs
  a valid session.
- `web-ui-shell`: auth screens before the workspace; the rail gains an account entry and shows
  Monitoring only to admins.
- `monitoring-dashboard`: endpoints and view restricted to admins; sessions show the account.
- `agent-telemetry`: spans carry an opaque user id attribute.

## Impact

- New: `storage/` tables and Alembic migration (`users`, `sessions`, `auth_tokens`,
  `login_attempts`, `owner_id` on thread tables and `user_id` on `turns`), `api/routers/v1_auth.py`,
  `api/routers/v1_account.py`, `api/services/auth/` (passwords, sessions, tokens, throttle,
  mailer), `api/core/session_guard.py`, `api/__main__.py` `create-admin` subcommand,
  `config/auth.py` + `config/mail.py` with `[auth]` and `[mail]` in `config/settings.toml`.
- Changed: every router (`Depends(current_user)`), `api/services/threads.py` and the thread
  repositories (owner scoping), `api/services/monitoring/` (admin dependency, user column),
  `app/telemetry.py` (user id attribute), `frontend/src` (auth feature, `apiClient` 401
  handling, rail entry), `compose.yaml` (`mailpit`, dev profile).
- Dependencies: `argon2-cffi`, `email-validator`. No change to `agent/`, `tools/`, `models/`.
- Secrets: `ECOFATE_SESSION_SECRET` (cookie signing / token pepper), `SMTP_PASSWORD`, read <!-- pragma: allowlist secret -->
  from the environment only.
- Breaking: the UI and API are no longer usable without an account. The command line program
  (`python -m app`) and the evaluations are unchanged and need no account.
