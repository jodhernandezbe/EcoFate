# agent-telemetry Specification

## Purpose
Records every agent run on the monitoring platform (Logfire) as one trace: the session, every
model call and every tool call, each with its timing and token usage. This lets an assessor or
developer see exactly what the agent did and what it cost.

## Requirements

### Requirement: Monitoring configured at the program edge
The command-line program and the web server SHALL configure monitoring once, at start-up, from
a `[telemetry]` configuration section (service name, environment, whether monitoring is
enabled, whether spans are also printed to the console). The agent, the tools and the models
SHALL NOT configure monitoring or depend on it. When monitoring is disabled in configuration,
runs SHALL behave exactly as before and record nothing.

#### Scenario: Disabled
- **WHEN** `[telemetry].enabled` is false and the agent runs
- **THEN** the answer is unchanged and no span is recorded

#### Scenario: Invalid configuration
- **WHEN** a `[telemetry]` value is missing or of the wrong type
- **THEN** loading the configuration raises an error naming the key

### Requirement: Traces sent only with a write token
Spans SHALL be exported to Logfire only when a Logfire write token is available (the
`LOGFIRE_TOKEN` environment variable or the project credentials written by
`logfire projects use`). Without one, the run SHALL still complete and nothing SHALL leave the
machine. The test suite SHALL never export spans.

#### Scenario: No write token
- **WHEN** the agent runs with monitoring enabled and no write token
- **THEN** the run completes and no request is made to Logfire

### Requirement: One trace per session run
Each command-line run SHALL be recorded as one session span. Each web chat turn SHALL be
recorded as one turn span. Both SHALL carry a session id: a new id per command-line run, and the
conversation thread id for web turns, so every turn of a thread can be found by that id. Both
SHALL also carry the user's question, the configured model name and an outcome (`ok` or
`error`). Every model call and every tool call made during the run, including the scope and
completion checks, SHALL be recorded as a span nested in that trace. Each model span SHALL carry
the model's prompt, completion and token usage. Each tool span SHALL carry the tool name,
arguments, result and duration.

#### Scenario: Tool call nested in the session
- **WHEN** a command-line run makes two model calls and one tool call
- **THEN** one trace holds the session span with two model spans and one tool span beneath it, the tool span naming the tool

#### Scenario: Web turns share the thread id
- **WHEN** two turns run on the same thread
- **THEN** both turn spans carry that thread's id as the session id

#### Scenario: Failed run still traced
- **WHEN** the agent raises during a run
- **THEN** the session or turn span ends with outcome `error` and the spans recorded before the failure are kept

### Requirement: Usage and cost on the trace
When a session or turn span ends, the system SHALL set on it the number of model calls, the
input, cached input and output tokens, the estimated cost in USD, and the cost status, all
computed by the usage cost meter. A web turn span SHALL carry both the turn's totals and the
thread's running session totals. The cost status SHALL be `estimate`, `lower_bound` or
`unpriced`, and an unpriced cost SHALL be left absent, never recorded as zero.

#### Scenario: Priced session
- **WHEN** a session's model calls all report usage and the model is priced
- **THEN** the session span carries the token totals and a cost with status `estimate`

#### Scenario: Unpriced model
- **WHEN** the configured model has no price entry
- **THEN** the span carries the token totals, status `unpriced` and no cost value

### Requirement: No secrets in spans
No span or span attribute SHALL contain an API key (the user's OpenAI key or an operator key), a
Logfire write or read token, a key-encryption key, a session or account token, a password, a
connection-string password, or any part of one. Spans SHALL be scrubbed with the same patterns
and protected values as the log redaction.

#### Scenario: Keys stored during a run
- **WHEN** a run uses the user's OpenAI key and the Census and CompTox operator keys
- **THEN** none of the recorded spans contains any of those keys

#### Scenario: Database error in a span
- **WHEN** a span records an exception whose text contains the database URL with its password
- **THEN** the recorded span does not contain the password

### Requirement: Spans carry an opaque user id
Each web turn's session span SHALL carry the signed-in user's id under the attribute name
configured in the telemetry settings. The id SHALL be the account's random identifier, never
the email, the password hash or anything derived from them. Command-line runs SHALL carry no
user id.

#### Scenario: Web turn
- **WHEN** a signed-in user runs a turn with telemetry enabled
- **THEN** the turn's session span has the user id attribute set to that user's id and contains no email

#### Scenario: Command-line run
- **WHEN** the command-line program runs
- **THEN** its session span has no user id attribute
