# web-ui-server Specification

## Purpose

The local web program that serves the split-screen interface and runs the exposure assessor
agent for each chat turn, streaming its progress to the browser as typed events.

## Requirements

### Requirement: Single-command local launch
The system SHALL start the web program with one command that serves both the API and the
built frontend from the same origin. It SHALL bind only to the loopback interface on the host
and port read from configuration, and SHALL refuse to start with a clear message when the
built frontend is missing. With the container flag, it SHALL instead bind to the container
bind address read from configuration (a loopback or the unspecified address), on the same
port; the flag SHALL NOT change the host and port used as the program's origin.

#### Scenario: Launch
- **WHEN** the user runs the launch command after building the frontend
- **THEN** the interface is served at the configured loopback address and the API answers under `/api`

#### Scenario: Frontend not built
- **WHEN** the launch command runs and the built frontend directory does not exist
- **THEN** the program exits with a message naming the build command, and no server starts

#### Scenario: Non-loopback host configured
- **WHEN** the configured host is not a loopback address
- **THEN** loading the configuration raises an error naming the host key

#### Scenario: Container launch
- **WHEN** the launch command runs with the container flag
- **THEN** the server listens on the configured container bind address and port, and the origin checks still use the configured host and port

### Requirement: Cross-site requests are rejected
Every state-changing endpoint (chat turns, saving or clearing the key, resetting a thread)
SHALL reject requests whose `Origin` (or, without one, `Referer`) is not the program's own
origin, and every endpoint SHALL reject requests whose `Host` is not the configured host and
port, whatever address the server is bound to, so a third-party web page cannot spend tokens
or change the key.

#### Scenario: Foreign origin
- **WHEN** a `POST` to the chat endpoint carries `Origin: https://example.com`
- **THEN** the response is 403 and the agent is not run

#### Scenario: Same origin
- **WHEN** a `POST` carries the program's own origin
- **THEN** the request is processed

#### Scenario: DNS-rebinding host
- **WHEN** a request arrives with a `Host` header other than the configured host and port
- **THEN** the response is 403

#### Scenario: Container bind does not widen the host check
- **WHEN** the server runs with the container flag and a request carries `Host: 0.0.0.0:8000`
- **THEN** the response is 403

### Requirement: Chat turn streaming
A chat turn SHALL be submitted as a `POST` to the versioned chat-stream endpoint with a thread identifier and the user's message, and
SHALL be answered with a `text/event-stream` of JSON events, each with a `type` and a monotonically
increasing `seq`, in this vocabulary:
- `turn_started` (thread id, turn id);
- `scope` (in or out of scope);
- `guardrail_pivot` (the in-character redirect text, when out of scope);
- `tool_status` with phase `started` (call id, tool name, human-readable step label) or
  `finished` (call id, status `ok` or `error`, short summary), never including raw tool payloads;
- `workspace_update` (the full current workspace state of the thread);
- `token` (assistant text fragment) and `assistant_message` (final text);
- `usage` (this turn's and the session's token and cost totals);
- `error` (a user-safe message and a correlation id);
- `turn_finished`.
The stream SHALL always end with `turn_finished`, including after an error.

#### Scenario: In-scope turn with tools
- **WHEN** a turn makes two tool calls and then answers
- **THEN** the stream contains `turn_started`, `scope`, a started/finished `tool_status` pair per call, at least one `workspace_update`, the assistant text, `usage` and `turn_finished`, in `seq` order

#### Scenario: Agent failure mid-turn
- **WHEN** the chat model raises during a turn
- **THEN** the stream emits `error` with a generic message and a correlation id, then `turn_finished`

#### Scenario: Provider has no credits
- **WHEN** the model provider refuses a turn because the account has no credits left
- **THEN** the stream emits `error` saying so plainly and pointing to the provider's billing, with a correlation id, then `turn_finished`; the provider's own text is not shown

#### Scenario: Other provider failures
- **WHEN** the provider rejects the key, rate-limits the request, cannot be reached or reports a server error
- **THEN** the `error` message says which of these happened and what to do, from a fixed set of messages

#### Scenario: No key configured
- **WHEN** a chat turn is submitted and no key is stored
- **THEN** the stream emits `error` saying the key must be set in Settings, then `turn_finished`, and no model is built

### Requirement: One wire contract between frontend and backend
The frontend SHALL interact with the system only through the backend's HTTP API and event
stream; it SHALL NOT call the agent, the tools or external assessment services directly (only
basemap tiles are fetched by the browser). Every request body, response body, event and the
dashboard state SHALL have one schema, published by the backend as a machine-readable
document; the frontend's types SHALL be generated from that document, and a check SHALL fail
when the generated types are out of date. The agent and its tools SHALL NOT depend on the
backend or the frontend.

#### Scenario: Contract drift
- **WHEN** an event field is renamed in the backend schema and the frontend types are not regenerated
- **THEN** the contract check fails

#### Scenario: Agent independent of the web
- **WHEN** the command-line program runs
- **THEN** no backend or frontend module is imported

### Requirement: Step labels are human-readable
Each started `tool_status` event SHALL carry a short label for the step, looked up by tool name from
configuration (e.g. the emissions inventory tool reads as "Queried EPA TRI releases"), falling
back to the tool name when no label is configured.

#### Scenario: Configured label
- **WHEN** the emissions inventory tool starts
- **THEN** its event label is the configured text, not the function name

#### Scenario: Unlabelled tool
- **WHEN** a tool without a configured label starts
- **THEN** its label is the tool name

### Requirement: Conversation threads
The program SHALL keep each thread's message history, dashboard state and session usage in
the database, so follow-up turns see earlier turns, also after the program restarts or when
another process serves the next turn. Clearing the workspace in the UI SHALL reset the thread
it shows. The program SHALL delete threads that have been idle longer than the configured
retention period; a thread running a turn SHALL NOT be deleted. A thread SHALL be resettable,
and only one turn per thread SHALL run at a time, across every process that serves the
program.

#### Scenario: Follow-up turn
- **WHEN** a second turn is sent on the same thread
- **THEN** the agent receives the first turn's messages and the dashboard keeps the earlier facilities

#### Scenario: Follow-up after a restart
- **WHEN** the program restarts between the first and the second turn of a thread
- **THEN** the agent receives the first turn's messages and the dashboard keeps the earlier facilities

#### Scenario: Reset
- **WHEN** the thread is reset
- **THEN** its history, dashboard and session usage are cleared

#### Scenario: Reset during a turn
- **WHEN** a reset is requested while the thread is running a turn
- **THEN** the request is answered 409 and the running turn is unaffected

#### Scenario: Concurrent turn on one thread
- **WHEN** a turn is submitted while another turn of the same thread is still running
- **THEN** the second request is answered 409 and the running turn is unaffected

#### Scenario: Retention limit
- **WHEN** a thread has been idle longer than the configured retention period
- **THEN** it is deleted with its history, dashboard and usage, and a later snapshot request for it is answered 404

#### Scenario: Running thread not evicted
- **WHEN** a thread older than the retention period is running a turn at purge time
- **THEN** it is not deleted

### Requirement: Leak-free errors
Error responses and error events SHALL contain only a message and a correlation id; the message is generic, or one of a fixed set of plain-language messages for known provider failures (no credits, rejected key, rate limit, unreachable, server error) and for a missing key or keychain. It is never the provider's or the exception's own text.
They SHALL NOT include exception text, tracebacks, request headers, request bodies or any
key material; the details SHALL go only to the (redacted) server log under the same
correlation id.

#### Scenario: Unhandled exception
- **WHEN** an endpoint raises an exception whose message contains `sk-` followed by a key
- **THEN** the HTTP response body contains neither the exception text nor the key, and the server log entry is redacted

#### Scenario: Validation error
- **WHEN** a request body fails validation
- **THEN** the response names the invalid field but does not echo submitted values

### Requirement: Thread snapshot
`GET /api/v1/chat/threads/{thread_id}` SHALL return, for a thread the program holds, the
thread's user and assistant messages in order (text only, without tool calls or tool
results), its latest workspace state (or the empty state before any tool result) and its session
usage, all in the shapes of the shared wire contract. A thread the program does not hold SHALL
be answered 404 with the generic error body. The endpoint SHALL NOT run the agent or change the
thread, apart from marking it as recently used. Its responses SHALL NOT contain keys,
exception text or request headers. A malformed thread id SHALL be answered 422.

#### Scenario: Snapshot of a held thread
- **WHEN** a thread with two finished turns is requested
- **THEN** the response lists its four user and assistant messages in order, the workspace last sent for it, and its session usage

#### Scenario: Unknown thread
- **WHEN** a thread id the program does not hold is requested
- **THEN** the response is 404 with a generic message and a correlation id

#### Scenario: Snapshot during a turn
- **WHEN** a thread is requested while its turn is running
- **THEN** the response holds what has been recorded so far and the running turn is unaffected

### Requirement: Confirmation request event
The chat turn stream SHALL carry a typed event that presents an open confirmation request:
the thread it belongs to, a request identifier, and one entry per missing value with its field
name, chemical or facility, the units the entry accepts (the target unit first), and the
plausible range. The event SHALL be sent before the turn finishes, and the turn SHALL end
after it without an answer being required to close the stream.

#### Scenario: Turn ends with an open request
- **WHEN** the agent stops to ask about missing values
- **THEN** the stream sends the confirmation request event, then the turn-finished event, and the request remains open in the thread

#### Scenario: Event shape matches the wire contract
- **WHEN** the event is serialized
- **THEN** it validates against the published schema, and the frontend types are regenerated from that schema

### Requirement: Answers as a turn input
A chat turn SHALL be able to carry the user's answers to an open confirmation request in place
of a text message. The answers SHALL name the request identifier and give, for each entry,
either proceed without or a numeric value with its unit. The server SHALL validate the
answers against the open request and reject answers for a request that is closed, belongs to
another thread, or does not list the entry.

#### Scenario: Valid answers start the next turn
- **WHEN** the user confirms an open request with one value and one proceed without
- **THEN** the turn runs with those answers, and the answered entries are no longer open

#### Scenario: Answers for a closed request
- **WHEN** answers arrive for a request that was already answered
- **THEN** the server rejects the turn with a clear error and changes nothing in the thread

#### Scenario: Answers for an entry not in the request
- **WHEN** answers name a field that the open request does not list
- **THEN** that answer is rejected and the request stays open

### Requirement: Values are validated on the server
The server SHALL validate every entered value against its entry's accepted units and plausible
range before any tool runs, using the same rules as the frontend. The frontend check is for
convenience only and SHALL NOT be the only check.

#### Scenario: Browser sends a value the server rejects
- **WHEN** an answer carries a value outside the plausible range, even though the browser allowed it
- **THEN** the server rejects the answer, reports the reason, and keeps the request open
