## ADDED Requirements

### Requirement: Live turn status in the chat
While a turn is queued or running the chat SHALL show, under the streaming assistant message, a
one-line status from the latest `turn_status` event: waiting for a worker with the approximate
number of turns ahead, thinking, or the label of the step that is running. The header status
indicator SHALL include the queued state. A **Stop** control SHALL be shown while the turn runs;
it cancels the turn, after which the chat shows the interruption with its Resume button. When
the page is reloaded during a turn the chat SHALL reattach to it and continue from the last
event it had, without duplicating messages or tool pills. When the connection drops the chat
SHALL reattach from the last event received. No dashboard panel SHALL change.

#### Scenario: Queued
- **WHEN** a turn is waiting with two turns ahead
- **THEN** the status line says it is waiting for a worker with about two ahead

#### Scenario: Running a step
- **WHEN** a `turn_status` event names the step "Fetching chemical properties"
- **THEN** the status line shows that label

#### Scenario: Stop
- **WHEN** the user presses Stop during a turn
- **THEN** the turn ends as interrupted with reason `cancelled` and a Resume button appears

#### Scenario: Reload during a turn
- **WHEN** the page is reloaded while a turn runs
- **THEN** the chat shows the messages so far and keeps streaming the same turn, with each tool pill shown once
