## MODIFIED Requirements

### Requirement: Agent turns run in a background worker
Every new, resumed and follow-up chat turn SHALL run as one task on the `chat` queue, and every
background tool job as one task on the `tools` queue, each served by its own worker process
pool (Celery with a Redis broker), never inside the API process that received the request. The
API SHALL record the turn as `queued`, enqueue its task and answer at once with the turn's event
stream. The number of tasks run at once per pool SHALL come from configuration. When the broker
cannot be reached the API SHALL answer 503 with a fixed message and mark the turn `failed`,
never leaving it `queued`.

#### Scenario: Turn enqueued
- **WHEN** a chat turn is submitted
- **THEN** a turn record is `queued`, one task is enqueued on the `chat` queue, and the API process does not call the chat model

#### Scenario: Broker down
- **WHEN** a chat turn is submitted and Redis cannot be reached
- **THEN** the response is 503 with a fixed message and the turn record is `failed`

#### Scenario: Short turn not behind long work
- **WHEN** the `tools` pool is busy with assessment jobs and a user sends a short question
- **THEN** the question's turn is taken by the `chat` pool without waiting for those jobs

### Requirement: Worker settings come from configuration
The names of both queues, the concurrency, prefetch, soft and hard time limits of each pool, the
visibility timeout, heartbeat interval, stale age, event stream length and lifetime, the per-user
cap on open jobs, the list of heavy tools, and the name of the environment variable holding the
Redis URL SHALL come from the `[worker]` settings; none SHALL be hard-coded. The loader SHALL
reject non-positive numbers, booleans used as numbers, a visibility timeout not above either
pool's hard limit, a hard limit not above its soft limit, and a heavy tool that is not a
registered tool.

#### Scenario: Limits out of order
- **WHEN** the settings give a soft time limit greater than the hard time limit for either pool
- **THEN** loading the settings raises at start-up

#### Scenario: Unknown heavy tool
- **WHEN** the heavy-tool list names a tool that is not registered
- **THEN** loading the settings raises at start-up
