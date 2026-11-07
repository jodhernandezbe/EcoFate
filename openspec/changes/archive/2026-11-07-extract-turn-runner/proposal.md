## Why

`api/services/agent_runner.py` does two jobs in one module: it *runs* a turn (reads the keys,
builds the agent, opens the telemetry span, meters usage, streams the LangGraph updates,
classifies provider failures) and it *presents* the turn to the browser (SSE event models,
step labels, workspace projection, user-facing error text). `add-background-agent-worker`
moves the running half into a Celery worker. If the worker imports it from `api/`, the two
transports (HTTP and the queue) depend on each other, the root rule "nothing imports `api`"
gains a permanent exception, and every change to the web layer can break the worker.

Splitting first, as a refactor with no behaviour change, lets the later changes add code
instead of moving it: `add-resumable-agent-turns` classifies interruptions in one place, and
the worker calls the same runner the API calls today.

## What Changes

- New package `app/turns/`: `execute_turn(...)`, an async generator of transport-neutral
  `TurnEvent`s (frozen dataclasses: text delta, tool started, tool finished with its message,
  scope redirect, confirmation needed, usage, failure with a reason code, finished). It owns
  key provision for the turn, agent build, run config, callbacks, the session span, usage
  recording and failure classification (`FailureReason`, no user-facing text).
- `protect_secrets`, `redact` and the redaction filter move from `api/core/logging_filter.py`
  to `app/redaction.py`; `api/core/logging_filter.py` keeps only the uvicorn log config and
  imports them.
- `api/services/agent_runner.py` becomes a presenter: it calls `execute_turn`, translates each
  `TurnEvent` into the existing wire events (`api/schemas/chat.py`), applies step labels,
  rebuilds the workspace from tool messages, records pending confirmations, and maps a
  `FailureReason` to the fixed messages in `api/services/provider_errors.py`.
- An import-boundary test: `app` never imports `api`; `api` and (later) `worker` reach the
  runner only through `app.turns`.
- No change to the wire contract, the event order, the UI, the CLI output or any spec'd
  behaviour.

## Capabilities

### New Capabilities

- `turn-execution`: a transport-neutral turn runner with its event vocabulary, used by every
  front end (web API now, background worker later).

### Modified Capabilities

(none; `web-ui-server` behaviour is unchanged and its existing tests are the safety net)

## Impact

- New: `app/turns/__init__.py`, `app/turns/events.py`, `app/turns/runner.py`,
  `app/turns/failures.py`, `app/redaction.py`.
- Changed: `api/services/agent_runner.py` (presenter only), `api/core/logging_filter.py`,
  `api/services/provider_errors.py` (maps `FailureReason` to text), `app/CLAUDE.md`,
  `api/CLAUDE.md`, root `CLAUDE.md` dependency line if needed, README architecture section.
- Tests: `tests/app/turns/` (new), `tests/api/` unchanged and green, a golden event-sequence
  test recorded before the move and asserted after it.
- `add-resumable-agent-turns` and `add-background-agent-worker` build on `app.turns`.
