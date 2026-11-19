# background-tool-jobs Specification

## Purpose

Let heavy tool work run in the background so the chat stays responsive: a heavy tool call
starts a recorded job and answers at once, the agent can report the job's progress, and an
automatic follow-up turn explains the result when the job ends.

## Requirements

### Requirement: Heavy tool calls start a background job
A tool marked heavy in configuration (initially only `assess_facilities`) SHALL NOT run inside
the agent turn. Its call SHALL validate its arguments, record a job and enqueue it on the
`tools` queue, then answer the tool call at once with the job id, the status `queued` and the
queue position, plus a fixed note on how to talk about it (started, not done; no result,
figure, count or facility name; the result comes in a follow-up). The tool's description SHALL
stay the tool's own, so the model chooses it as it did when it ran in the turn. The job SHALL run
the same tool code with the same arguments and the user's answers to missing values. The values
the chemical lookup lists as missing SHALL still be asked for before any job is queued. A turn
in which a heavy tool queued a job SHALL NOT be reviewed by the completion check: its work is
running, and sending the agent back to work would make it write results it has not seen.

#### Scenario: Assessment queued
- **WHEN** the agent calls `assess_facilities` for a chemical with nothing missing
- **THEN** a job record is `queued`, one task is enqueued on the `tools` queue, and the tool call is answered at once with the job id and `queued`

#### Scenario: No completion review after queuing
- **WHEN** the agent replies that the queued assessment has started
- **THEN** the completion check does not send it back to work and the reply ends the turn

#### Scenario: Missing values asked first
- **WHEN** the chemical lookup lists a missing value the user has not answered
- **THEN** the turn stops to ask for it and no job is queued

### Requirement: Jobs are recorded durably
Each job SHALL be stored in PostgreSQL with its id, owner, thread, tool name, input, status
(`queued`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`), queue time, start and
end times, a heartbeat, its result (the model's view and the workspace artifact) and, on
failure, a fixed reason without secrets. Only the job's owner SHALL read it; another user's job
id SHALL be answered as not found.

#### Scenario: Job finishes
- **WHEN** a job's tool returns
- **THEN** its record is `succeeded` with its result and end time

#### Scenario: Foreign job
- **WHEN** a user asks for a job that belongs to another user
- **THEN** the answer is the same as for an unknown id

### Requirement: The thread is free while a job runs
The turn that started a job SHALL end as soon as the model has answered, and release the
thread. The user SHALL be able to send new messages on that thread while the job runs; they
SHALL run as ordinary turns.

#### Scenario: Question during a job
- **WHEN** a job of the thread is running and the user sends a message
- **THEN** the message runs as a turn and is not answered 409

### Requirement: The agent can report a job's progress
A quick tool, `check_job_status`, SHALL return the status, queue position, elapsed time and, when
ended, a short outcome of a job of the current thread. It SHALL be offered to a turn only once
its thread has a job; a turn of a thread without jobs SHALL get the tools it had before
background jobs existed. The agent SHALL describe queued or running work as started, never as
finished, and SHALL NOT invent results of a job that has not ended.

#### Scenario: No job, no status tool
- **WHEN** a turn runs in a thread that has no job
- **THEN** `check_job_status` is not among the turn's tools

#### Scenario: Asked while running
- **WHEN** the user asks how the assessment is going while its job runs
- **THEN** the agent calls `check_job_status` and reports it as running with its elapsed time

### Requirement: A finished job starts a follow-up turn
When a job ends succeeded, failed or interrupted (not when the user cancelled it), the system
SHALL start one follow-up turn in its thread,
on the `chat` queue, whose input is the job's outcome; it SHALL explain the result as a normal
answer would and fill the workspace from the job's artifact. When another turn of the thread is
running, the follow-up SHALL wait until it ends. A follow-up SHALL run at most once per job.

#### Scenario: Result explained
- **WHEN** an assessment job succeeds and the thread is idle
- **THEN** a follow-up turn runs, the workspace shows the job's facilities, and the answer explains them

#### Scenario: Thread busy at the end
- **WHEN** a job ends while another turn of its thread is running
- **THEN** the follow-up starts only after that turn ends

### Requirement: Job limits, cancel and recovery
The number of queued and running jobs per user SHALL be capped by configuration; a heavy call over
the cap SHALL be answered with a fixed message and no job. A user SHALL be able to cancel a queued
or running job; a running job stops after its current step. Jobs SHALL have soft and hard time
limits and a heartbeat from configuration; a job whose heartbeat is older than the stale age, or
whose worker is lost, SHALL become `interrupted` and be resumable, never re-run automatically.

#### Scenario: Over the cap
- **WHEN** a user already has the configured number of open jobs and the agent starts another
- **THEN** the tool call is answered that the limit is reached and no job is recorded

#### Scenario: Worker lost
- **WHEN** the worker running a job stops without finishing it
- **THEN** the job becomes `interrupted` after the stale age and is not re-run by itself

### Requirement: A thread-level event stream
The API SHALL offer one event stream per thread, read like today's turn stream (numbered events,
reconnect with the last id, nothing missed or repeated), carrying job status changes and the
follow-up turn's events, so a page that is open, or reopened, sees a job end and its follow-up.

#### Scenario: Page reopened
- **WHEN** the user reloads the page while a job runs and the job then finishes
- **THEN** the page shows the job ending and the follow-up answer

### Requirement: Same security rules as turns
A job's task message SHALL carry the job id and owner id only. The worker that runs the job SHALL
read the operator keys from its environment and SHALL NOT need the user's OpenAI key; the API
SHALL never decrypt a key. Job input and results SHALL pass the same redaction as tool results.

#### Scenario: Task payload
- **WHEN** a job is enqueued
- **THEN** its message holds exactly the job id and the owner id
