## MODIFIED Requirements

### Requirement: Chat turn streaming
A chat turn SHALL be submitted as a `POST` to the versioned chat-stream endpoint with a thread identifier and the user's message, and
SHALL be answered with a `text/event-stream` of JSON events, each with a `type` and a monotonically
increasing `seq`, in this vocabulary:
- `turn_started` (thread id, turn id, and whether the turn is being resumed);
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
A recoverable failure SHALL be reported with `turn_interrupted` instead of `error`.

#### Scenario: In-scope turn with tools
- **WHEN** a turn makes two tool calls and then answers
- **THEN** the stream contains `turn_started`, `scope`, a started/finished `tool_status` pair per call, at least one `workspace_update`, the assistant text, `usage` and `turn_finished`, in `seq` order

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

### Requirement: Thread snapshot
`GET /api/v1/chat/threads/{thread_id}` SHALL return, for a thread the program holds, the
thread's user and assistant messages in order (text only, without tool calls or tool
results), its latest workspace state (or the empty state before any tool result), its session
usage, and, when its latest turn is interrupted, that interruption (reason, whether it can be
resumed, the fixed message), all in the shapes of the shared wire contract. A thread the
program does not hold SHALL be answered 404 with the generic error body. The endpoint SHALL
NOT run the agent or change the thread, apart from marking it as recently used. Its responses
SHALL NOT contain keys, exception text or request headers. A malformed thread id SHALL be
answered 422.

#### Scenario: Snapshot of a held thread
- **WHEN** a thread with two finished turns is requested
- **THEN** the response lists its four user and assistant messages in order, the workspace last sent for it, and its session usage

#### Scenario: Unknown thread
- **WHEN** a thread id the program does not hold is requested
- **THEN** the response is 404 with a generic message and a correlation id

#### Scenario: Snapshot during a turn
- **WHEN** a thread is requested while its turn is running
- **THEN** the response holds what has been recorded so far and the running turn is unaffected

#### Scenario: Snapshot of an interrupted thread
- **WHEN** a thread whose latest turn is `interrupted` with reason `out_of_credits` is requested
- **THEN** the response includes that interruption as resumable with its fixed message

## ADDED Requirements

### Requirement: Resume endpoint
`POST /api/v1/chat/threads/{thread_id}/resume` SHALL resume the thread's interrupted turn and
answer with the same `text/event-stream` event vocabulary as a chat turn, starting with
`turn_started` marked as resumed and ending with `turn_finished`. It SHALL take no message. It
SHALL answer 404 for a thread the program does not hold, 409 with a fixed message when the
thread has no resumable turn, has reached the resume cap, or is running a turn, and 422 for a
malformed thread id; a refused resume SHALL NOT change the thread or its turns.

#### Scenario: Resume streams the rest of the turn
- **WHEN** a resumable thread is resumed and the run calls one more tool and answers
- **THEN** the stream contains `turn_started` (resumed), a `tool_status` pair for that tool only, the assistant text, `usage` and `turn_finished`

#### Scenario: Nothing to resume
- **WHEN** the latest turn of the thread is `completed`
- **THEN** the response is 409 with a fixed message and the thread is unchanged

#### Scenario: Resume while running
- **WHEN** a resume is requested while the thread's turn is running
- **THEN** the response is 409 and the running turn is unaffected
