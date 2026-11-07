# resumable-turns Specification

## Purpose

Durable status for every chat turn and the rules for continuing one that stopped: which
failures interrupt a turn rather than fail it, how a resume continues from the last checkpoint
under a fresh step budget and a resume cap, how a new message abandons an interrupted turn, and
how turns left running by a stopped server are recovered at start-up.

## Requirements

### Requirement: Durable turn status
Every chat turn SHALL have a record in the database with a status of `queued`, `running`,
`interrupted`, `completed` or `failed`, the time it was created, started, last updated and
finished, its resume count and, when interrupted or failed, a reason. At most one turn per
thread SHALL be `queued` or `running` at a time, enforced by the database, so a second turn on
the same thread is refused even when it reaches a different process. A status SHALL change
only along `queued -> running -> (interrupted | completed | failed)` and
`interrupted -> running` (resume) or `interrupted -> failed` (abandoned).

#### Scenario: Turn recorded
- **WHEN** a turn runs to its answer
- **THEN** its record goes from `running` to `completed` with start and finish times

#### Scenario: Second turn on a busy thread
- **WHEN** a turn is submitted while the thread's turn is `running`
- **THEN** the request is answered 409 and no second record is created

#### Scenario: Illegal transition refused
- **WHEN** code tries to move a `completed` turn back to `running`
- **THEN** the repository raises and the record is unchanged

### Requirement: Recoverable failures interrupt the turn
A turn that stops because the provider reports no credits, rejects the key, rate-limits the
request, cannot be reached or fails on its side, because the run reached the step limit, or
because the process running it stopped, SHALL become `interrupted` with the reason
`out_of_credits`, `bad_key`, `rate_limited`, `provider_down`, `step_limit` or `worker_lost`.
Any other failure SHALL make the turn `failed` and SHALL NOT be resumable. The reason SHALL be
derived from the failure's status code, error code or class, never from its message text.

#### Scenario: Credits run out mid-turn
- **WHEN** the provider answers a model call with 429 and code `insufficient_quota` after two tools finished
- **THEN** the turn is `interrupted` with reason `out_of_credits` and the two tool results are kept in the thread's checkpoint

#### Scenario: Step limit
- **WHEN** the run raises the graph's recursion-limit error
- **THEN** the turn is `interrupted` with reason `step_limit`

#### Scenario: Unexpected exception
- **WHEN** a node raises an exception that is not a provider failure or the step limit
- **THEN** the turn is `failed` and no resume is offered

### Requirement: Resume continues from the last checkpoint
Resuming an interrupted turn SHALL continue the same thread's graph run from its last
checkpoint without a new input: the user's message SHALL NOT be added again and tool calls
whose results are in the checkpoint SHALL NOT be run again. The resumed run SHALL use the
configured step limit afresh. Its model calls SHALL be added to the same turn's usage. A turn
SHALL be resumable only when it is the thread's latest turn, it is `interrupted`, its resume
count is below the configured maximum per turn, and the checkpoint has a next step; otherwise
the resume SHALL be refused without changing the turn. Each resume SHALL increment the resume
count, including one that is interrupted again.

#### Scenario: Resume after adding credits
- **WHEN** a turn interrupted by `out_of_credits` is resumed
- **THEN** the model is called with the history including the earlier tool results, no new user message is added, no finished tool runs again, and the turn completes

#### Scenario: Resume after the step limit
- **WHEN** a turn interrupted by `step_limit` is resumed
- **THEN** the run continues with a full step budget

#### Scenario: Cap reached
- **WHEN** a turn has been resumed the configured maximum number of times and is interrupted again
- **THEN** a further resume is refused with a fixed message and the turn stays `interrupted`

#### Scenario: Nothing left to run
- **WHEN** a resume is requested but the checkpoint has no next step
- **THEN** the turn is marked `completed` and the resume is refused

### Requirement: A new message abandons an interrupted turn
When the user sends a new message on a thread whose latest turn is `interrupted`, the program
SHALL first answer every tool call of the last assistant message that has no result with a
tool result saying the call was not run because the turn was interrupted, then mark the
interrupted turn `failed` with reason `superseded`, then run the new turn. The history sent to
the model SHALL never contain a tool call without a result.

#### Scenario: Message instead of resume
- **WHEN** a turn was interrupted after the model asked for two tools and the user sends a new message
- **THEN** the thread gains two "not run" tool results, the old turn is `failed/superseded`, and the new turn's first model call receives a history where every tool call has a result

### Requirement: Waiting for missing values is not an interruption
A turn that ends by asking the user for missing values SHALL be `completed`, and SHALL NOT be
offered for resume; the answers flow continues as before. A turn that carries answers and is
then interrupted SHALL resume with those answers already recorded, without asking for them
again.

#### Scenario: Turn stops to ask
- **WHEN** a turn ends with a confirmation request
- **THEN** the turn is `completed` and the snapshot reports no interrupted turn

#### Scenario: Interrupted answer turn
- **WHEN** a turn carrying answers is interrupted by `rate_limited` and then resumed
- **THEN** the resumed run uses the supplied values and no new confirmation request is made for them

### Requirement: Turns left running at start-up are interrupted
When the program starts, every turn still recorded as `running` or `queued` SHALL be marked
`interrupted` with reason `worker_lost`, so it can be resumed and its thread is not blocked.

#### Scenario: Server restarted mid-turn
- **WHEN** the server stops during a turn and starts again
- **THEN** that turn is `interrupted/worker_lost`, the thread accepts a resume or a new message, and no turn is left `running`
