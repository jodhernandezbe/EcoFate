# persistent-storage Specification

## Purpose

The PostgreSQL store of the web program: durable conversation state, versioned migrations,
the cross-process turn lease, retention by idle time, start-up and health behaviour, and the
contract shared by the real and the in-memory thread stores.

## Requirements

### Requirement: PostgreSQL holds conversation state
The web program SHALL store every thread's message history (as LangGraph checkpoints),
session usage, tool calls and results, latest workspace, open confirmation request, and the
values the user supplied or declined in PostgreSQL, so they survive a restart of the program
and are visible to every process connected to the same database. Every stored row SHALL carry
a `user_id` column (nullable until accounts exist). The command-line program SHALL NOT need
the database.

#### Scenario: Restart survival
- **WHEN** a thread has two finished turns and the web program is restarted
- **THEN** the thread snapshot after the restart shows both turns, the same workspace and the same session usage, and a third turn receives the earlier messages

#### Scenario: Second process sees the thread
- **WHEN** one process records a turn and another process connected to the same database reads the thread
- **THEN** the second process returns the same messages, workspace and usage

#### Scenario: Command line without a database
- **WHEN** `python -m app "..."` runs with no `DATABASE_URL` set
- **THEN** the run completes without connecting to a database

### Requirement: Schema managed by migrations
The schema of the program's own tables SHALL be created and changed only by versioned
migrations, applied by an explicit command (`python -m storage upgrade`, wrapped by
`make migrate` and by a one-shot compose service), never implicitly by the web process. The
checkpoint tables SHALL be created by the checkpoint library's own idempotent setup. The web
program SHALL refuse to start, with a fixed message naming the migrate command, when the
database is not at the latest migration.

#### Scenario: Fresh database
- **WHEN** the migrate command runs against an empty database
- **THEN** every table exists and the reported revision is the latest

#### Scenario: Round trip
- **WHEN** the migrations are applied, rolled back to the base and applied again
- **THEN** each step succeeds and the final schema equals the first

#### Scenario: Not migrated
- **WHEN** the web program starts against a database below the latest migration
- **THEN** it exits with a message naming `make migrate` and serves nothing

### Requirement: Connection only from the environment
The database URL SHALL be read only from the environment variable named in `[database]`, and
SHALL NOT appear in configuration files, code, images, responses or logs. A missing or blank
URL SHALL stop the web program at start-up with a fixed message naming the variable. Passwords
in PostgreSQL URLs SHALL be masked by the log redaction, and bound statement parameters SHALL
NOT appear in database error logs.

#### Scenario: Missing URL
- **WHEN** the web program starts and `DATABASE_URL` is unset or blank
- **THEN** it exits with a message naming `DATABASE_URL`

#### Scenario: Password in a log line
- **WHEN** a log record contains `postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate` <!-- pragma: allowlist secret -->
- **THEN** the written line contains the user, host and database but not `s3cr3t`

#### Scenario: Query failure
- **WHEN** a statement carrying a user's supplied value fails
- **THEN** the log line names the statement but not the value

### Requirement: One turn per thread across processes
Claiming a thread for a turn SHALL be a single atomic database operation that takes a lease
for `[database].turn_lease_seconds`; a claim SHALL fail while another unexpired lease exists,
whichever process holds it. Releasing SHALL clear the lease and SHALL be safe to repeat. An
expired lease (its process crashed) SHALL NOT block a new claim.

#### Scenario: Concurrent claims
- **WHEN** two processes claim the same idle thread at the same moment
- **THEN** exactly one claim succeeds and the other request is answered 409

#### Scenario: Crashed process
- **WHEN** a process holding a lease dies and the lease time passes
- **THEN** a new turn on that thread can be claimed

#### Scenario: Release twice
- **WHEN** a turn's lease is released twice
- **THEN** both calls succeed and the thread is idle

### Requirement: Stored rows are untrusted on read
Rows read back from the database SHALL be decoded with shape and type checks (finite numbers,
no boolean as a number, known message types, valid workspace model); a row that fails SHALL be
treated as absent and logged with its thread id, never coerced or guessed.

#### Scenario: Malformed workspace
- **WHEN** a thread's stored workspace does not validate against the workspace model
- **THEN** the snapshot returns the empty workspace and a warning is logged with the thread id

#### Scenario: Non-finite supplied value
- **WHEN** a stored supplied value is NaN
- **THEN** it is not returned among the thread's supplied values

### Requirement: Idle threads are purged
The web program SHALL periodically (every `[database].purge_interval_minutes`) delete threads
not used for `[database].thread_retention_days`, together with their checkpoints and every
dependent row. A thread holding an unexpired lease SHALL NOT be purged.

#### Scenario: Old idle thread
- **WHEN** a thread was last used longer ago than the retention and is idle
- **THEN** the purge deletes it, its checkpoints, usage, tool messages, workspace, pending request and answers

#### Scenario: Busy thread kept
- **WHEN** an old thread holds an unexpired lease at purge time
- **THEN** it is not deleted

### Requirement: Health reflects the database
`GET /api/health` SHALL answer 200 `{"status": "ok"}` only when the database answers a trivial
query within `[database].health_timeout_seconds`, and 503 `{"status": "unavailable"}`
otherwise, without exception text, the URL or any credential.

#### Scenario: Database down
- **WHEN** the database is stopped and the health endpoint is called
- **THEN** it answers 503 with `{"status": "unavailable"}` within the health timeout

#### Scenario: Database up
- **WHEN** the database answers
- **THEN** the health endpoint answers 200 with `{"status": "ok"}`

### Requirement: Fake and real stores honour one contract
Unit tests SHALL use an in-memory thread store that implements the same protocol as the
PostgreSQL store, and one contract test suite SHALL run against both: against the fake in the
default test run, and against a real PostgreSQL under the `postgres` marker when
`ECOFATE_TEST_DATABASE_URL` is set. The default test run SHALL NOT need a database.

#### Scenario: Default run
- **WHEN** `uv run pytest` runs without `ECOFATE_TEST_DATABASE_URL`
- **THEN** the contract suite passes against the fake and no database connection is opened

#### Scenario: Database run
- **WHEN** `make test-db` runs
- **THEN** the same contract suite passes against PostgreSQL, each test in a schema that is dropped afterwards
