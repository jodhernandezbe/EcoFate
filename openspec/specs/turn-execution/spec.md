# turn-execution Specification

## Purpose

The one transport-neutral turn runner in the program layer: it runs an agent turn (keys,
agent build, telemetry span, usage, failure classification) and yields turn events that each
front end (the web API now, a background worker later) presents in its own way.

## Requirements

### Requirement: Transport-neutral turn runner
The system SHALL run one agent turn through a single runner in the program layer that takes
the thread id, the turn input, and its collaborators from the caller (a key loader, a chat
model factory, the checkpointer, the user's values and a usage store), and yields
transport-neutral turn events (turn began, agent started, text delta, final text, tool calls,
tool started, tool finished, tool results, scope passed, scope redirect, confirmation needed,
usage, failure with a reason code and correlation id, done). The runner SHALL NOT import the web layer, the wire schemas, step labels or user-facing message text,
and every front end (the web API and the background worker) SHALL run turns only through it.

#### Scenario: Runner independent of the web layer
- **WHEN** the import graph of the program layer is inspected
- **THEN** no module under it imports the web API package

#### Scenario: Same events as before the split
- **WHEN** a scripted fake model runs a turn through the chat stream endpoint
- **THEN** the endpoint emits the same event types, in the same order and with the same payload shapes as before the runner was extracted

#### Scenario: Every turn ends with usage and done
- **WHEN** a turn succeeds, is redirected by the scope check, or fails
- **THEN** the runner's last two events are the usage event and the done event

### Requirement: Failures carry a reason, not text
The runner SHALL turn a provider or service failure into a failure event carrying one reason
code from a closed set and a correlation id under which it logged the failure, and SHALL NOT
carry the exception text; the web layer SHALL map the reason to its fixed user-facing message.

#### Scenario: Out of credits
- **WHEN** the model call fails with HTTP 429 and error code `insufficient_quota`
- **THEN** the runner yields a failure event with reason `out_of_credits` and the browser receives the existing out-of-credits message

#### Scenario: Unexpected error
- **WHEN** the model call raises an exception that matches no known provider failure
- **THEN** the runner yields reason `unexpected`, the browser receives the generic message with a correlation id, and the exception text appears in no event

### Requirement: Keys provided for the turn only
The runner SHALL receive the turn's keys from its caller (through a key loader it calls inside
the turn), provide them to the tools and to the log redaction only while the turn runs, and
release them on success, failure and cancellation alike.

#### Scenario: Keys released after a failure
- **WHEN** a turn raises inside the graph
- **THEN** after the runner finishes, no key holder holds a key and the redaction set no longer contains the turn's keys
