## MODIFIED Requirements

### Requirement: Chat turn streaming
A chat turn SHALL be submitted as a `POST` to the versioned chat-stream endpoint with a thread identifier and the user's message, and
SHALL be answered with a `text/event-stream` of JSON events, each with a `type` and a monotonically
increasing `seq`, read from the turn's event stream as the background worker writes it, in this
vocabulary:
- `turn_started` (thread id, turn id, and whether the turn is being resumed);
- `turn_status` (phase `queued` with the approximate number of turns ahead, `running`,
  `thinking`, or `running_tool` with the step label);
- `scope` (in or out of scope);
- `guardrail_pivot` (the in-character redirect text, when out of scope);
- `tool_status` with phase `started` (call id, tool name, human-readable step label) or
  `finished` (call id, status `ok` or `error`, short summary), never including raw tool payloads;
- `workspace_update` (the full current workspace state of the thread);
- `token` (assistant text fragment) and `assistant_message` (final text);
- `turn_interrupted` (the interruption reason, whether the turn can be resumed, and a fixed
  user-facing message);
- `usage` (this turn's and the session's token and cost totals);
- `error` (a user-safe message and a correlation id);
- `turn_finished`.
The stream SHALL always end with `turn_finished`, including after an error or an interruption.
A recoverable failure SHALL be reported with `turn_interrupted` instead of `error`. Each event
SHALL carry its `seq` as the SSE event id, so a client can reattach from it.

#### Scenario: In-scope turn with tools
- **WHEN** a turn makes two tool calls and then answers
- **THEN** the stream contains `turn_started`, `turn_status` `queued` and `running`, `scope`, a started/finished `tool_status` pair per call, at least one `workspace_update`, the assistant text, `usage` and `turn_finished`, in `seq` order

#### Scenario: Agent failure mid-turn
- **WHEN** the chat model raises an exception that is not a known provider failure during a turn
- **THEN** the stream emits `error` with a generic message and a correlation id, then `turn_finished`

#### Scenario: Provider has no credits
- **WHEN** the model provider refuses a turn because the account has no credits left
- **THEN** the stream emits `turn_interrupted` with reason `out_of_credits`, resumable, and a message saying so plainly and pointing to the provider's billing, then `usage` and `turn_finished`; the provider's own text is not shown

#### Scenario: Other provider failures
- **WHEN** the provider rejects the key, rate-limits the request, cannot be reached or reports a server error
- **THEN** the stream emits `turn_interrupted` whose reason and message say which of these happened and what to do, from a fixed set of messages

#### Scenario: No key configured
- **WHEN** a chat turn is submitted and no key is stored
- **THEN** the stream emits `error` saying the key must be set in Settings, then `turn_finished`, and no model is built

#### Scenario: Step limit reached
- **WHEN** the run reaches the configured step limit
- **THEN** the stream emits `turn_interrupted` with reason `step_limit`, resumable, then `usage` and `turn_finished`

#### Scenario: Client disconnects
- **WHEN** the browser closes the stream while the turn is running
- **THEN** the turn keeps running in the worker and finishes normally

## ADDED Requirements

### Requirement: Reattach to a turn's events
`GET /api/v1/chat/turns/{turn_id}/events` SHALL stream the events of a turn of a thread the
caller may see, from the event after the `seq` given in the `Last-Event-ID` header (from the
first event when absent), and SHALL end after `turn_finished`. A turn the caller may not see
or that does not exist SHALL be answered 404; a malformed id 422. When the turn's events have
expired the endpoint SHALL answer 410 with a fixed message, and the client restores the thread
from its snapshot. The thread snapshot SHALL include the id of a turn that is `queued` or
`running`, so a reloaded page can reattach.

#### Scenario: Reattach after reload
- **WHEN** a page reloads during a turn and requests the turn's events with `Last-Event-ID: 41`
- **THEN** the stream starts at `seq` 42 and ends with `turn_finished`

#### Scenario: Events expired
- **WHEN** the events of a long-finished turn are requested
- **THEN** the response is 410 with a fixed message

### Requirement: Cancel a turn
`POST /api/v1/chat/turns/{turn_id}/cancel` SHALL request cancellation of a `queued` or
`running` turn of a thread the caller may see and answer 202; the turn's stream then ends with
`turn_interrupted` (reason `cancelled`), `usage` and `turn_finished`. A finished turn SHALL be
answered 409, an unknown or not visible turn 404, a malformed id 422.

#### Scenario: Cancel accepted
- **WHEN** a running turn is cancelled
- **THEN** the response is 202 and the turn's stream ends with `turn_interrupted` reason `cancelled`
