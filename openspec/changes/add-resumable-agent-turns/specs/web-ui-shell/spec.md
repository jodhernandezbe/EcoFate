## ADDED Requirements

### Requirement: Resume an interrupted turn from the chat
When a turn is interrupted, the chat SHALL keep the assistant's partial text and tool pills,
show the interruption's fixed message beneath them, and, when the turn can be resumed, a
**Resume** button that resumes it in place: the resumed events SHALL continue the same
assistant message. For a rejected key the chat SHALL also offer to open Settings. While a turn
is running the Resume button SHALL be disabled and say why. A turn that cannot be resumed SHALL
show its message without a Resume button. The composer SHALL stay usable, and sending a new
message SHALL replace the Resume button with the new turn. After a page reload the chat SHALL
restore the interruption and its Resume button from the thread snapshot. The status indicator
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

#### Scenario: Reload keeps Resume
- **WHEN** the page is reloaded on a thread whose latest turn is interrupted and resumable
- **THEN** the chat shows the interruption message and the Resume button again

#### Scenario: Cap reached
- **WHEN** an interrupted turn is no longer resumable
- **THEN** its message is shown without a Resume button
