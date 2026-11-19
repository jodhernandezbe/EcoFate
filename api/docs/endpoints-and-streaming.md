[← Documentation index](../../README.md#documentation) · [API](../README.md)

# Endpoints, streaming and the daily limit

## Endpoints

All routes need a signed-in session (401 otherwise) except the health check, the static UI, the
client display settings and the public auth routes. The machine-readable contract is
`frontend/src/types/schema.json`.

| Method and path | What it does |
|---|---|
| `GET /api/health` | liveness plus database check |
| `POST /api/v1/auth/signup`, `/verify`, `/resend`, `/signin`, `/signout`, `/forgot`, `/reset` | account lifecycle (public) |
| `GET /api/v1/auth/me` | the signed-in user |
| `POST /api/v1/account/password`, `/sign-out-everywhere`, `/delete` | account menu actions |
| `POST /api/v1/chat/stream` | start a turn: records it `queued`, enqueues it, streams its events (SSE); 429 over the daily limit |
| `GET /api/v1/chat/turns/{id}/events` | reattach to a turn's event stream with `Last-Event-ID` (410 once expired) |
| `POST /api/v1/chat/turns/{id}/cancel` | ask for a stop after the current step (202; 409 finished; 404 unknown or another user's) |
| `POST /api/v1/chat/threads/{id}/resume` | queue the latest interrupted turn again |
| `GET /api/v1/chat/current-thread` | lets a reloaded page find its thread |
| `GET /api/v1/chat/threads/{id}` | the thread's state and workspace |
| `GET /api/v1/chat/threads/{id}/report` | the Word report |
| `DELETE /api/v1/chat/threads/{id}` | clear the workspace (the conversation too) |
| `GET /api/v1/facilities/{frs_id}` | a facility as the thread's workspace shows it |
| `GET`, `POST`, `DELETE /api/v1/settings/openai-key` | status of, save, or clear the user's OpenAI key (never returns it) |
| `GET /api/v1/settings/keys` | whether each data service is available on this installation |
| `GET /api/v1/settings/client` | display settings for the browser (thresholds, digits, map styles); public |
| `GET /api/v1/usage/quota` | the signed-in user's daily figures |
| `GET /api/v1/monitoring/sessions`, `/sessions/{id}` | recorded sessions (administrators only; 404 otherwise) |

The turn stream is SSE: each event carries its position as the SSE id, so a reloaded page or a
dropped connection reattaches and misses nothing. How a turn travels:
[architecture](../../docs/architecture.md#a-turns-path) and [worker](../../worker/README.md#a-turns-sequence).

## Daily limit

Each user may start a limited number of new agent turns per UTC day (the count restarts at 00:00 UTC). The operator sets it in `[limits]` in `config/settings.toml` (`daily_turns_per_user`, `enabled`, `admin_exempt`, `retention_days`, `exhausted_message`); a change takes effect on restart.

- **Counted:** a new message the server accepts (signed in, thread free). A turn that stops before it reaches the model and cannot be resumed (for example, no OpenAI key) is given back, once.
- **Free:** resuming an interrupted turn and answering the assistant's confirmation request. Both continue a turn that was already counted.
- **Over the limit** the server answers `429` with the reset time and `Retry-After`, before anything runs. The header shows "N turns left today" and, at none, the chat input says when it resets in local time.

The command line program and the evaluations are not limited. `GET /api/v1/usage/quota` returns the signed-in user's figures.
