# background-agent-worker Specification

## Purpose

Agent turns of the web program run in a bounded background worker pool (Celery over
Redis), never in the API process: id-only task messages, keys obtained by the worker for
the turn only, a per-turn event stream readers reattach to, cooperative cancellation, time
limits and lost-worker recovery that leave turns resumable, settings from configuration and
an in-process mode for tests.

## Requirements

### Requirement: Agent turns run in a background worker
Every new and resumed chat turn SHALL run as one task in a separate worker process pool
(Celery with a Redis broker), never inside the API process that received the request. The API
SHALL record the turn as `queued`, enqueue its task and answer at once with the turn's event
stream. The number of turns run at once per worker SHALL come from configuration. When the
broker cannot be reached the API SHALL answer 503 with a fixed message and mark the turn
`failed`, never leaving it `queued`.

#### Scenario: Turn enqueued
- **WHEN** a chat turn is submitted
- **THEN** a turn record is `queued`, one task is enqueued, and the API process does not call the chat model

#### Scenario: Broker down
- **WHEN** a chat turn is submitted and Redis cannot be reached
- **THEN** the response is 503 with a fixed message and the turn record is `failed`

### Requirement: Task messages carry ids only
A task message SHALL carry only identifiers (turn id, and the thread and user ids if needed).
It SHALL NOT carry an API key, a session or reset token, the encryption key, the user's
message text or any tool payload. The input of a new turn SHALL be stored with the turn record
in the database and read by the worker.

#### Scenario: Serialized task inspected
- **WHEN** a turn is enqueued for a user with a stored OpenAI key
- **THEN** the serialized task message contains the turn id and none of: the key, the message text, the session cookie value

### Requirement: The worker obtains keys for the turn only
The worker SHALL decrypt the turn owner's OpenAI key itself when the task starts, read the
operator's service keys from its own environment, give them to the model and the tools only
for that task, protect them from the logs for that task, and release them when the task ends,
whether it completes, is interrupted or raises. A turn whose owner has no stored key SHALL be
marked `failed` with the fixed "add your OpenAI key" message and SHALL NOT build a model.

#### Scenario: Keys released after failure
- **WHEN** a task raises an unexpected exception
- **THEN** no key holder still holds a key after the task and the log line for the failure contains no key

#### Scenario: No key stored
- **WHEN** the owner of a queued turn has no stored OpenAI key
- **THEN** the turn is `failed`, its stream carries the fixed message, and no chat model is built

### Requirement: Turn events are kept for reattaching
The worker SHALL write each event of a turn, in `seq` order, to a per-turn event stream in
Redis bounded by a configured maximum length and expiring a configured time after
`turn_finished`. A reader SHALL be able to read the events of a turn from any `seq` onward, so
a browser that reconnects with the last `seq` it received misses no event and sees none twice.
Events SHALL contain no key, token or exception text.

#### Scenario: Reconnect after a reload
- **WHEN** a reader that received events up to `seq` 41 reconnects with that `seq`
- **THEN** it receives events from `seq` 42 onward, in order, including those emitted while it was away

#### Scenario: Stream expires
- **WHEN** the configured time has passed after `turn_finished`
- **THEN** the turn's event stream no longer exists in Redis

### Requirement: Running turns can be cancelled
A cancel request for a `queued` or `running` turn SHALL make the worker stop after the current
graph step (a queued turn SHALL not start), mark the turn `interrupted` with reason
`cancelled`, emit `turn_interrupted`, `usage` and `turn_finished`, and keep the checkpoint so
the turn can be resumed. Cancelling a finished turn SHALL be refused with 409. The worker
process SHALL NOT be killed to cancel a turn.

#### Scenario: Stop mid-turn
- **WHEN** the user cancels a turn while a tool is running
- **THEN** the tool's result is kept, no further model call is made, and the turn is `interrupted/cancelled` and resumable

#### Scenario: Cancel a finished turn
- **WHEN** a cancel request names a `completed` turn
- **THEN** the response is 409 and the turn is unchanged

### Requirement: Lost and timed-out turns become resumable
Tasks SHALL be acknowledged only after they finish, prefetched one at a time, and SHALL NOT be
re-run automatically when a worker is lost. The broker's visibility timeout SHALL exceed the
task's hard time limit. A task that reaches its soft time limit SHALL mark its turn
`interrupted` with reason `time_limit`. The worker SHALL record a heartbeat on the running turn
at a configured interval; a turn whose worker was lost, or whose heartbeat is older than a
configured age, SHALL be marked `interrupted` with reason `worker_lost`. No turn SHALL stay
`running` without a live worker.

#### Scenario: Worker killed mid-turn
- **WHEN** the worker process running a turn is killed
- **THEN** within the configured stale age the turn is `interrupted/worker_lost`, it is not re-run automatically, and it can be resumed

#### Scenario: Soft time limit
- **WHEN** a turn runs past the soft time limit
- **THEN** the turn is `interrupted/time_limit` and its stream ends with `turn_interrupted`, `usage` and `turn_finished`

### Requirement: Worker settings come from configuration
The queue name, worker concurrency, prefetch, soft and hard time limits, visibility timeout,
heartbeat interval, stale age, event stream length and lifetime, and the name of the
environment variable holding the Redis URL SHALL come from the `[worker]` settings; none SHALL
be hard-coded. The loader SHALL reject non-positive numbers, booleans used as numbers, and a
visibility timeout not above the hard limit or a hard limit not above the soft limit.

#### Scenario: Limits out of order
- **WHEN** the settings give a soft time limit greater than the hard time limit
- **THEN** loading the settings raises at start-up

### Requirement: Tests run the worker in-process
With the eager setting on, a task SHALL run in the calling process through the same code, and
events SHALL go through an in-memory event stream with the same reading semantics, so the test
suite needs no Redis and no running worker.

#### Scenario: Eager turn
- **WHEN** the default test suite submits a chat turn with a fake model
- **THEN** the turn runs in-process and the stream carries the same event sequence as with a real worker
