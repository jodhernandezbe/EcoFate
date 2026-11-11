## 1. Settings and storage

- [x] 1.1 Add `[limits]` to `config/settings.toml` (`enabled`, `daily_turns_per_user`, `admin_exempt`, `retention_days`, `exhausted_message`) with comments, and `config/limits.py`; negative tests: 0, negative, `true`, non-integer limit; blank message.
- [x] 1.2 `storage/`: `daily_turn_usage(user_id FK cascade, day, turns, PK(user_id, day))`, `turns.quota_refunded`; async repository `consume(user_id, limit) -> int | None` (single `INSERT ... ON CONFLICT DO UPDATE ... WHERE turns < :limit RETURNING`, day from `now() AT TIME ZONE 'UTC'`), `refund(user_id, turn_id)` (once, guarded by `quota_refunded`), `usage(user_id)`; purge rows older than `retention_days` in the existing retention job; Alembic migration up/down.

## 2. API

- [x] 2.1 `api/services/quota.py`: `QuotaService` (applies? limit, consume, refund, status with reset time and seconds until reset).
- [x] 2.2 `api/routers/v1_chat.py`: after auth, the key check and the thread claim, and before `plan_turn`, consume unless the body answers the thread's pending confirmation; on refusal release the claim and raise 429 with body (`detail`, `limit`, `resets_at`, `correlation_id`) and `Retry-After`. The resume endpoint never consumes.
- [x] 2.3 `api/services/agent_runner.py`: refund when a counted turn ends before its first model call.
- [x] 2.4 `api/routers/v1_usage.py` `GET /api/v1/usage/quota` (session required); `api/schemas/quota.py`; regenerate the contract (`uv run python -m scripts.export_contract`, `npm --prefix frontend run gen:types`).

## 3. Frontend

- [x] 3.1 `hooks/useQuota.ts` (load, refresh after `turn_finished`, update from a 429); header element "N turns left today" next to the usage meter in `TopHeaderBar.tsx`; chat input disabled reason with the local reset time. Follow `frontend/DESIGN.md` with the `ui-craft` skill; `/ui-check` light and dark. Do not otherwise change the Overview, Map or Chat panels.
- [x] 3.2 Vitest: turns-left text, limit reached disables input with reason, 429 keeps the typed message, exempt admin shows nothing.

## 4. Tests (one negative test per rule)

- [x] 4.1 Counting against the compose Postgres: limit reached refuses; five concurrent consumes with one left accept exactly one; new UTC day accepts again (frozen DB time or explicit day parameter in the repository test).
- [x] 4.2 Not counted: unauthenticated (401), missing key, busy thread (409), resume, valid confirmation answer; forged confirmation answer rejected and not free.
- [x] 4.3 Refund: failure before the first model call refunds once (second refund attempt is a no-op); provider failure after a model call does not refund.
- [x] 4.4 Configuration: disabled quota never counts; admin exempt vs. counted when `admin_exempt = false`.
- [x] 4.5 429 response: body fields, `Retry-After`, no model built (fake factory not called), thread not left busy.
- [x] 4.6 Quota endpoint: values, exempt flag, 401 without a session, no other user's figures.

## 5. Documentation

- [x] 5.1 README: the daily limit, where to change it (`[limits]` in `config/settings.toml`), what counts and what is free; `api/CLAUDE.md` (quota checked in the chat router before any work); note in `openspec/ROADMAP.md` only if a shared decision changed.

## 6. Verification

- [x] 6.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, `uv run bandit -c pyproject.toml -r agent app api commons config evals models prompts tools`, function-length check, `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice).
- [x] 6.2 Run `/security-audit` on the change and resolve every confirmed finding.
- [x] 6.3 Live check with `docker compose up` and `daily_turns_per_user = 2`: run two turns, confirm the header reads 0 left and the third is refused with 429 and `Retry-After`; interrupt and resume a turn without the count changing; confirm an exempt admin is not limited.
