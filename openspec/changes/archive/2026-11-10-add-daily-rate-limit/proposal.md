## Why

With accounts (step 4) and BYOK (step 5) each user pays for their own model calls, but every
turn still costs the operator: CPU and memory for the read-across model and the screening
calculations, the operator's CompTox and Census quotas, Open-Meteo's non-commercial call
budget (under 10,000 a day), Logfire volume and, from step 7, worker slots. One user, or one
script with a stolen session, can exhaust them for everyone. A per-user daily quota of agent
turns, set by the operator in configuration rather than in code, protects the service and
makes the cost of the deployment predictable. This is roadmap step 6.

## What Changes

- Each user may start at most `[limits].daily_turns_per_user` agent turns per UTC day, reset
  at 00:00 UTC. The value lives in `config/settings.toml`; changing it needs no code change
  and takes effect on restart.
- A turn is counted when the server accepts it (signed in, OpenAI key stored, thread not
  busy). Resuming an interrupted turn and answering the assistant's confirmation request are
  free, because they continue a turn already counted. A turn that fails before its first
  model call (for example a key that cannot be decrypted) is refunded.
- `[limits].admin_exempt` decides whether admins are counted; `[limits].enabled` turns the
  quota off for local single-user runs.
- Counting is one atomic `INSERT ... ON CONFLICT DO UPDATE ... WHERE turns < limit RETURNING`
  on a `daily_turn_usage(user_id, day, turns)` table, so concurrent requests from one user,
  across API processes, can never exceed the limit.
- Over the limit the chat endpoint answers **429** with a fixed message, the UTC reset time in
  the body and a `Retry-After` header, before any agent, model or worker work starts.
- `GET /api/v1/usage/quota` returns the user's limit, used, remaining, reset time and whether
  they are exempt. The header shows the remaining turns next to the usage meter; when none are
  left, the chat input is disabled and says when it resets (in the user's local time).
- The command line program and the evaluations are not limited.

## Capabilities

### New Capabilities

- `daily-turn-quota`: the per-user daily quota, its configuration, atomic counting, free
  resumes and confirmations, refunds, the 429 answer and the quota endpoint.

### Modified Capabilities

- `web-ui-shell`: the header shows the remaining turns and the chat input explains an
  exhausted quota.

## Impact

- New: `[limits]` in `config/settings.toml` and `config/limits.py`; `storage/` table
  `daily_turn_usage` + async repository + Alembic migration; `api/services/quota.py`;
  `api/routers/v1_usage.py`; `api/schemas/quota.py` and regenerated frontend types;
  `frontend/src/hooks/useQuota.ts` and a small header element.
- Changed: `api/routers/v1_chat.py` (quota check before planning the turn), the resume and
  confirmation paths (marked free), `api/services/agent_runner.py` (refund on failure before
  the first model call), `TopHeaderBar.tsx` (remaining turns), chat input disabled state.
- No change to `agent/`, `tools/`, `models/`, the CLI or `evals/`.
