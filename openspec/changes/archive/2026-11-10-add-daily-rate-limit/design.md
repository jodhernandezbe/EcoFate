## Context

See proposal.md and `openspec/ROADMAP.md` ("Rate limit"). This builds on:

- `add-user-accounts`: every request has an authenticated `user_id` and `role`.
- `migrate-to-postgresql`: async `storage/` (SQLAlchemy async + psycopg 3), Alembic.
- `add-resumable-agent-turns`: a `turns` row per turn with status and reason, and a resume
  endpoint that continues an interrupted turn from its checkpoint.
- `web-ui-server` "Answers as a turn input": a confirmation answer is sent as the next
  `POST /api/v1/chat/stream` of the same thread with the pending request's answers.
- `add-background-agent-worker` (step 7, after this): the API enqueues the turn; the quota
  must be consumed in the API before enqueueing so the worker never sees an over-quota turn.

## Goals / Non-Goals

**Goals:**
- A hard, race-free per-user daily cap on new agent turns, configured in `settings.toml`.
- The user knows how many turns are left and when the quota resets, before typing.
- Continuing work already counted (resume, confirmation answer) never costs a turn.

**Non-Goals:**
- Token- or cost-based quotas (users pay their own tokens under BYOK).
- Per-user custom limits or paid tiers (a nullable `users.daily_turn_limit` override is an
  easy follow-up).
- Request-rate limiting of other endpoints; login throttling is in `add-user-accounts`, and
  network-level limits belong to the Caddy proxy in step 9.

## Decisions

1. **Unit = accepted turn.** Counting tokens would punish long assessments and duplicate the
   provider's own billing; a turn maps to the operator's real costs (tool calls, CPU, worker
   slot). *Alternative*: count model calls — rejected, unpredictable for the user.
2. **UTC day.** `day = (now in UTC).date()`, reset at 00:00 UTC for everyone; the UI shows
   the reset converted to the browser's local time. *Alternative*: per-user time zones —
   rejected, needs a profile setting and makes the cap gameable by changing zones.
3. **Atomic counter in Postgres.**
   `INSERT INTO daily_turn_usage (user_id, day, turns) VALUES (:u, :d, 1)
    ON CONFLICT (user_id, day) DO UPDATE SET turns = daily_turn_usage.turns + 1
    WHERE daily_turn_usage.turns < :limit RETURNING turns`
   — no row returned means the limit is reached. Single statement, no read-then-write race,
   correct across API replicas. The first insert of the day still has to respect a limit of
   at least 1 (validated in config). *Alternative*: Redis `INCR` with expiry — rejected
   because Redis arrives only in step 7 and the count must survive restarts; the repository
   is a small Protocol so it can move.
4. **Where the check runs.** In `v1_chat.chat_stream`, after authentication, the
   missing-key check and the thread claim, and before `plan_turn` or enqueueing. If the
   claim succeeds but the quota is exhausted, the claim is released and 429 returned.
   Order matters: a busy thread (409) or a missing key must not consume a turn.
5. **Free continuations.** The resume endpoint never calls the quota. A chat-stream request
   whose body answers the thread's pending confirmation request (validated by
   `plan_turn`'s existing check) is free; any other message is counted. The check of "is this
   an answer" reuses `api/services/confirmation.py`, so a forged answer to a non-existent
   request is rejected there as today (and would not be free).
6. **Refund.** If a counted turn ends before its first model call (key unreadable, guard
   setup error), `refund(user_id, day)` decrements once (`turns = greatest(turns - 1, 0)`),
   recorded on the `turns` row so a turn is never refunded twice. Turns that reached the
   model are not refunded, even if the provider then fails (they consumed resources; the
   user can resume them for free).
7. **Configuration.** `[limits]`: `enabled` (bool), `daily_turns_per_user` (int >= 1),
   `admin_exempt` (bool), `retention_days` (rows older than this are purged by the existing
   idle-retention job). Loaded by `config/limits.py`; `bool` is rejected where an int is
   expected (defensive rule). No limit value appears in Python code; tests build settings.
8. **429 body.** `{"detail": "<fixed message>", "resets_at": "<ISO 8601 UTC>", "limit": n,
   "correlation_id": ...}` plus `Retry-After` in seconds until reset. The message is fixed
   text in `[limits]` (not built from user input).
9. **UI.** `useQuota` fetches `/api/v1/usage/quota` on load and after each `turn_finished`
   (existing event). The header shows "N turns left today" beside the usage meter (hidden when
   the quota is disabled or the user is exempt). At zero the chat input is disabled with the
   reason and the local reset time, following the "Disabled controls say why" rule. A 429
   from the stream updates the same state. Overview, Map and Chat panel internals are not
   changed beyond the input's disabled reason.

## Risks / Trade-offs

- **Abuse via many accounts** → sign-up throttling and email verification (step 4) raise the
  cost; the operator can close sign-up. Residual risk accepted.
- **Clock skew between API replicas** → the day is computed by the database (`now() AT TIME
  ZONE 'UTC'`), not by each process.
- **Confirmation answers as a loophole** → only an answer to the thread's actual pending
  request is free, and a pending request exists only after a counted turn asked for it.
- **Changing the limit mid-day** → takes effect on restart; users already above a lowered
  limit are simply refused until reset.
- **Trade-off**: refunds only before the first model call keep the rule simple; a user who
  hits a provider error mid-turn resumes for free instead.

## Migration Plan

1. Migration adds `daily_turn_usage(user_id FK cascade, day date, turns int >= 0,
   PRIMARY KEY (user_id, day))` and `turns.quota_refunded bool default false`.
2. Ship with `[limits].enabled = true`, a modest default `daily_turns_per_user` chosen by the
   operator, and `admin_exempt = true`.
3. Rollback: the previous image ignores the table; the down migration drops it and the column.
