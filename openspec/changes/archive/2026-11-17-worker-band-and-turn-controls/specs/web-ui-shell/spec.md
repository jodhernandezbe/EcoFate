## MODIFIED Requirements

### Requirement: Resume an interrupted turn from the chat
When a turn is interrupted, the chat SHALL keep the assistant's partial text and tool pills,
mark the place it stopped with the word "Stopped", and show the interruption's fixed message in
the turn controls at the top of the chat, under its header, never inside the thread. When the turn
can be resumed, the controls SHALL offer a **Resume** button that resumes it in place: the resumed events SHALL continue the same
assistant message. For a rejected key the controls SHALL also offer to open Settings. While a turn
is running the Resume button SHALL be disabled and say why. A turn that cannot be resumed SHALL
show its message without a Resume button. The composer SHALL stay usable, and sending a new
message SHALL replace the Resume button with the new turn. When the chat restores a held thread
from its snapshot, it SHALL restore the interruption and its Resume button with it (restoring the
thread after a page reload is a separate change). The status indicator
SHALL show that the turn stopped. No dashboard panel SHALL change.

#### Scenario: Out of credits
- **WHEN** a turn is interrupted with reason `out_of_credits`
- **THEN** the message says the account has no credits and how to add them, and a Resume button is shown

#### Scenario: Resume continues the message
- **WHEN** the user presses Resume and the run answers
- **THEN** the answer streams into the same assistant message, after its earlier tool pills, and the Resume button disappears

#### Scenario: Rejected key
- **WHEN** a turn is interrupted with reason `bad_key`
- **THEN** the chat offers both Resume and a control that opens the Settings drawer

#### Scenario: Restored thread keeps Resume
- **WHEN** the chat restores a held thread whose latest turn is interrupted and resumable from its snapshot
- **THEN** the chat shows the interruption message and the Resume button again

#### Scenario: Cap reached
- **WHEN** an interrupted turn is no longer resumable
- **THEN** its message is shown without a Resume button

#### Scenario: Controls above the thread
- **WHEN** the latest turn is interrupted and resumable
- **THEN** Resume and the fixed message are in the bar under the chat header, and the thread shows only "Stopped" after the partial answer, with no button

### Requirement: Live turn status in the chat
While a turn is queued or running the chat SHALL show, in the turn controls at the top of the
chat under its header (never inside the thread), a one-line status from the latest `turn_status` event: waiting for a worker with the approximate
number of turns ahead, thinking, or the label of the step that is running. The header status
indicator SHALL include the queued state. A **Stop** control SHALL be shown beside that status while the turn runs;
it cancels the turn, after which the chat shows the interruption with its Resume button. When
the page is reloaded during a turn the chat SHALL reattach to it and continue from the last
event it had, without duplicating messages or tool pills (a reloaded page restores its current
thread from the server, never from browser storage). When the connection drops the chat SHALL
reattach from the last event received. No dashboard panel SHALL change.

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

#### Scenario: Stop above the thread
- **WHEN** a turn runs
- **THEN** its status and Stop are in the bar under the chat header, and no status line or Stop is drawn under the streaming message
