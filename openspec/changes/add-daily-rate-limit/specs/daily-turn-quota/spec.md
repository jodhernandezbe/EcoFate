## ADDED Requirements

### Requirement: Daily turn quota from configuration
The web program SHALL limit each user to a number of new agent turns per UTC calendar day,
reset at 00:00 UTC. The limit, whether the quota is enabled, and whether administrators are
exempt SHALL be read from the `[limits]` section of the configuration file, and no limit value
SHALL be written in code. Loading the configuration SHALL reject a limit that is not a positive
integer (including a boolean). The command-line program and the evaluations SHALL NOT be
limited.

#### Scenario: Limit from configuration
- **WHEN** `[limits].daily_turns_per_user` is 3 and a user has started 3 turns today
- **THEN** the user's fourth new turn today is refused

#### Scenario: Reset at midnight UTC
- **WHEN** a user reached the limit before 00:00 UTC
- **THEN** after 00:00 UTC their next turn is accepted

#### Scenario: Invalid limit
- **WHEN** `daily_turns_per_user` is `0`, negative or `true`
- **THEN** loading the configuration raises an error naming the key

#### Scenario: Quota disabled
- **WHEN** `[limits].enabled` is false
- **THEN** no turn is counted or refused

#### Scenario: Admin exempt
- **WHEN** `admin_exempt` is true and an admin has started more turns than the limit today
- **THEN** the admin's turns are still accepted and a regular user's are still limited

### Requirement: Counting is atomic
A turn SHALL be counted in the application database with a single atomic statement that
increments the user's count for the day only while it is below the limit and reports whether
it did. Concurrent requests from one user, including requests reaching different processes,
SHALL never result in more accepted turns than the limit. The day SHALL be taken from the
database clock in UTC.

#### Scenario: Concurrent requests at the limit
- **WHEN** a user with one turn left sends five new turns at the same moment on five threads
- **THEN** exactly one is accepted and four are answered 429

### Requirement: Only new turns are counted
A turn SHALL be counted only after the request is authenticated, the user has an OpenAI key
stored and the thread was free; a request refused for any of those reasons SHALL NOT consume
quota. Resuming an interrupted turn and answering the thread's pending confirmation request
SHALL NOT be counted. A counted turn that ends before its first model call SHALL be refunded
once. A turn that reached the model SHALL NOT be refunded.

#### Scenario: Busy thread
- **WHEN** a turn is submitted on a thread whose turn is still running
- **THEN** it is answered 409 and the user's count is unchanged

#### Scenario: Resume is free
- **WHEN** a user at the limit resumes an interrupted turn
- **THEN** the resume runs and the count is unchanged

#### Scenario: Confirmation answer is free
- **WHEN** a user at the limit answers the assistant's pending confirmation request on that thread
- **THEN** the turn continues and the count is unchanged

#### Scenario: Forged answer is not free
- **WHEN** a request claims to answer a confirmation request the thread does not have pending
- **THEN** it is rejected as today and is not run for free

#### Scenario: Refund before the model
- **WHEN** a counted turn fails before its first model call
- **THEN** the user's count for the day goes back down by one, and only once

#### Scenario: Provider failure is not refunded
- **WHEN** a counted turn fails after a model call because the provider rate-limits it
- **THEN** the count is unchanged and the turn can be resumed for free

### Requirement: Over-quota answer
A new turn over the quota SHALL be refused with HTTP 429 before any agent, model, tool or
background work starts and before the thread is left marked busy. The body SHALL contain a
fixed user-safe message from configuration, the limit, the reset time as an ISO 8601 UTC
timestamp and a correlation id, and the response SHALL carry a `Retry-After` header with the
seconds until the reset.

#### Scenario: Refused turn
- **WHEN** a user over the limit submits a new turn
- **THEN** the response is 429 with the message, limit, reset time and `Retry-After`, no model is built, and the thread can take a turn again after the reset

### Requirement: Quota endpoint
`GET /api/v1/usage/quota` SHALL return, for the signed-in user, whether the quota applies to
them, the limit, the turns used today, the turns remaining and the reset time in UTC. It SHALL
require a session and SHALL NOT reveal any other user's usage.

#### Scenario: Quota status
- **WHEN** a user with a limit of 5 has started 2 turns today and asks for their quota
- **THEN** the response says the quota applies, limit 5, used 2, remaining 3 and the next 00:00 UTC

#### Scenario: Exempt admin
- **WHEN** an exempt admin asks for their quota
- **THEN** the response says the quota does not apply to them
