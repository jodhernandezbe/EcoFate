## Context

See proposal.md. Today (`api/services/agent_runner.py`, ~490 lines):

- Running: `_load_keys` / `_provided` (keys from `ServiceKeys`, `HOLDERS[...].provide`,
  `protect_secrets`), `_build` (agent with `ScopeGuard`, `CompletionGuard`, checkpointer),
  `_callbacks` / `_run_config` (usage recorder, `run_tracer`, recursion limit), the
  `session_span`, `agent.astream(..., stream_mode=["messages", "updates"])`, `explain(error)`.
- Presenting: `Token`, `ToolStatus`, `AssistantMessage`, `WorkspaceUpdate`, `Usage`,
  `ErrorEvent`, `TurnStarted`/`TurnFinished` from `api/schemas/chat.py`, step labels,
  `build_workspace` with `WorkspaceRules`, `request_event` for confirmations, the
  `ThreadStore` bookkeeping, `GENERIC_ERROR` with a correlation id.

`app/` is already "the program: builds the chat model and runs the agent" (`app/run.py` for
the CLI), imports `agent`, `config`, `tools.credentials`, and never imports `api`.

## Goals / Non-Goals

**Goals:**
- One runner, used by the web API now and by the Celery worker in
  `add-background-agent-worker`, that knows nothing about HTTP, SSE or the wire schemas.
- Zero behaviour change: same events, same order, same messages, same spans.
- Dependency direction stays one way: `api -> app`, `worker -> app`; transports never import
  each other.

**Non-Goals:**
- Moving the workspace projectors or wire schemas out of `api/` (they are presentation).
- Changing the CLI runner (`app/run.py`) beyond reusing shared helpers where it is free.
- Any persistence, resume or queue work (later changes).

## Decisions

1. **Transport-neutral events in `app/turns/events.py`.** Frozen dataclasses:
   `TextDelta(text)`, `ToolStarted(call_id, tool_name)`, `ToolFinished(call_id, tool_name,
   message: ToolMessage)`, `ToolCalls(message: AIMessage)` (for the workspace's tool-call
   bookkeeping), `ScopeRedirect(text)`, `ConfirmationNeeded(request: ConfirmationRequest)`,
   `TurnUsage(calls)`, `TurnFailed(reason: FailureReason)`, `TurnDone()`. The union is
   `TurnEvent`. No sequence numbers, labels or correlation ids: those are presentation.
   Alternative: reuse the pydantic wire events in `app/`, rejected: it makes the wire contract
   a dependency of the core and the worker.
2. **Failure classification in `app/turns/failures.py`.** `classify(exc) -> FailureReason`
   (`out_of_credits`, `rate_limited`, `bad_key`, `forbidden`, `provider_down`, `unreachable`,
   `user_facing`, `unexpected`) using the same duck-typed checks `provider_errors.explain`
   uses today (status code, error code, class names). `api/services/provider_errors.py` keeps
   only the reason -> fixed message table. `add-resumable-agent-turns` extends the enum.
3. **Keys are injected, not looked up.** `execute_turn` takes a `TurnKeys` value (OpenAI key
   required, service keys optional) from its caller; the API builds it from `ServiceKeys` as
   today, and later the worker builds it from the user key vault. `execute_turn` provides
   them to `HOLDERS` and `protect_secrets` for the turn and releases them on every exit path.
4. **Redaction moves to `app/redaction.py`.** The worker needs it and it holds no HTTP
   knowledge. `install_redaction` stays generic over logger names; `uvicorn_log_config` stays
   in `api/core/logging_filter.py`.
5. **Thread bookkeeping stays with the presenter.** The runner receives the checkpointer and
   the thread id; `ThreadStore` (pending confirmations, tool messages, workspace, usage) is
   updated by the API presenter from the events, so the worker in a later change publishes
   the same events and the API side does the same bookkeeping on relay.
6. **Safety net first.** Before moving code, add a golden test that runs a scripted fake model
   through `/api/v1/chat/stream` and stores the event types and payload shapes in order; the
   same test must pass after the move without edits.

## Risks / Trade-offs

- A refactor of the hottest module can change event order subtly -> the golden test and the
  existing `tests/api/` suite, unchanged.
- `ToolMessage` objects in events are LangChain types; acceptable inside one process. The
  worker change serialises them (`messages_to_dict`) for Redis.
- Function-length limit (18 lines) applies to the new modules; split helpers accordingly.

## Migration Plan

Pure code move, one commit. Rollback is a revert. No data or configuration changes.
