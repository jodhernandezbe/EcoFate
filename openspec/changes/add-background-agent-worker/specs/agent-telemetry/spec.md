## MODIFIED Requirements

### Requirement: One trace per session run
Each command-line run SHALL be recorded as one session span. Each web chat turn SHALL be
recorded as one turn span. Both SHALL carry a session id: a new id per command-line run, and the
conversation thread id for web turns, so every turn of a thread can be found by that id. Both
SHALL also carry the user's question, the configured model name and an outcome (`ok` or
`error`). Every model call and every tool call made during the run, including the scope and
completion checks, SHALL be recorded as a span nested in that trace. Each model span SHALL carry
the model's prompt, completion and token usage. Each tool span SHALL carry the tool name,
arguments, result and duration. A web turn that is run by the background worker SHALL stay one
trace: the trace context SHALL travel with the task (in its headers, never in its arguments),
the worker's run span SHALL be a child of the API's turn span, and it SHALL carry the same
session id and the seconds the turn waited in the queue.

#### Scenario: Tool call nested in the session
- **WHEN** a command-line run makes two model calls and one tool call
- **THEN** one trace holds the session span with two model spans and one tool span beneath it, the tool span naming the tool

#### Scenario: Web turns share the thread id
- **WHEN** two turns run on the same thread
- **THEN** both turn spans carry that thread's id as the session id

#### Scenario: Failed run still traced
- **WHEN** the agent raises during a run
- **THEN** the session or turn span ends with outcome `error` and the spans recorded before the failure are kept

#### Scenario: Trace spans API and worker
- **WHEN** a web turn is enqueued by the API and run by the worker
- **THEN** the API's turn span and the worker's run span share one trace id, the worker span carries the thread id as session id and the queue wait, and the model and tool spans are nested beneath the worker span
