# load-testing Specification

## Purpose

Show how the system behaves with many users at once, measured on the same compose stack that
runs in production, with a cost-free run and a small, budgeted real-model run.

## Requirements

### Requirement: Scripted multi-user load test
A load-test script SHALL simulate concurrent signed-in users against a running stack, each
sending a scripted mix of messages (a full assessment, a short question during a running job, a
status question, a resume), and SHALL run at 10, 25 and 50 concurrent users. It SHALL use a fake
chat model and recorded tool latencies by default, so it calls no paid service.

#### Scenario: No token cost by default
- **WHEN** the load test runs without the real-model option
- **THEN** no request reaches the model provider

### Requirement: Measurements reported
For each run the test SHALL report the time to the first answer, queue wait per queue, job
duration, turn duration, the share of requests answered 409, 429 or 5xx, follow-up turns started,
and worker CPU and memory, as percentiles (median, 95th, maximum) where they are durations.

#### Scenario: Short question under load
- **WHEN** 50 users run assessments and one asks a short question
- **THEN** the report shows that question's time to first answer and its queue wait on the `chat` queue

### Requirement: Budgeted real-model run
An optional run with the real chat model SHALL take the number of users and a spending cap, stop
starting new turns once the estimated cost reaches the cap, and report the actual estimated cost.

#### Scenario: Budget reached
- **WHEN** the estimated cost reaches the cap during a real-model run
- **THEN** no new turn is started and the report says the cap ended the run

### Requirement: Results documented
The results of each run SHALL be written to a page in `docs/` with the stack and settings used,
the date, the measurements and a short reading of where the limit is.

#### Scenario: Reproducible
- **WHEN** a reader opens the load-test page
- **THEN** it gives the command, the settings and the measurements of each run
