## MODIFIED Requirements

### Requirement: Only new turns are counted
A turn SHALL be counted only after the request is authenticated, the user has an OpenAI key
stored and the thread was free; a request refused for any of those reasons SHALL NOT consume
quota. Resuming an interrupted turn, answering the thread's pending confirmation request, and the
automatic follow-up turn started when a background job ends SHALL NOT be counted. A counted turn that ends before its first model call SHALL be refunded
once. A turn that reached the model SHALL NOT be refunded.

#### Scenario: Busy thread
- **WHEN** a turn is submitted on a thread whose turn (not a background job) is still running
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

#### Scenario: Follow-up is free
- **WHEN** a background job of a user at the limit ends and its follow-up turn runs
- **THEN** the follow-up runs and the count is unchanged
