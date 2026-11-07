## 1. Safety net

- [ ] 1.1 Add a golden test in `tests/api/` that runs a scripted fake model (tool call, tool result, confirmation request, final answer; plus a scope redirect and a provider failure case) through `/api/v1/chat/stream` and asserts the event types, order and payload shapes. Commit it green before moving any code.

## 2. Program layer

- [ ] 2.1 `app/redaction.py`: move `protect_secrets`, `redact`, `SecretRedactionFilter`, `install_redaction` from `api/core/logging_filter.py`; leave `uvicorn_log_config` there importing them; move their tests to `tests/app/test_redaction.py` unchanged. <!-- pragma: allowlist secret -->
- [ ] 2.2 `app/turns/events.py`: the `TurnEvent` dataclasses and union (frozen, no sequence numbers or text labels).
- [ ] 2.3 `app/turns/failures.py`: `FailureReason` and `classify(exc)`; move the duck-typed checks from `api/services/provider_errors.py`; table-driven tests including `bool` status codes and bodies of the wrong shape (negative tests).
- [ ] 2.4 `app/turns/runner.py`: `TurnKeys`, `execute_turn(...)` (key provision and release, agent build, run config, callbacks, session span, usage recording, `astream` translation into `TurnEvent`s, failure classification); each function within 18 lines; tests with a fake model: event sequence, keys released on success, failure and `CancelledError`, exception text absent from events.

## 3. Web layer as presenter

- [ ] 3.1 Rewrite `api/services/agent_runner.py` to call `execute_turn` and translate `TurnEvent`s into the wire events (sequence numbers, step labels, workspace rebuild, pending confirmation, usage summary, `GENERIC_ERROR` with correlation id); `provider_errors.py` maps `FailureReason` to the fixed messages.
- [ ] 3.2 The golden test from 1.1 and all of `tests/api/` pass with no edits.

## 4. Boundaries and docs

- [ ] 4.1 Import-boundary test (`tests/test_layering.py`): `app` imports nothing from `api`; nothing imports `api` (the worker change later adds `worker` to the "nothing imports" side, not as an exception).
- [ ] 4.2 Update `app/CLAUDE.md` (`turns/` is the one turn runner; `redaction.py`), `api/CLAUDE.md` (`agent_runner` presents, never runs the graph itself), README architecture section.

## 5. Verification

- [ ] 5.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, bandit, the function-length check, `uv run pre-commit run --all-files` (twice).
- [ ] 5.2 One live turn in the web UI (`uv run python -m api`) and one CLI run: same answer flow, same pills, same usage meter; a Logfire trace still shows the session span with model and tool calls.
