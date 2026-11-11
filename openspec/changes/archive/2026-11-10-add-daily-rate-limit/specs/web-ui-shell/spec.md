## ADDED Requirements

### Requirement: Remaining turns shown before typing
When the daily quota applies to the signed-in user, the header SHALL show the number of turns
left today next to the usage meter, refreshed when the page loads and after every finished
turn. When no turns are left, the chat input SHALL be disabled and SHALL say that the daily
limit was reached and when it resets, in the user's local time. A 429 answer from the chat
endpoint SHALL put the interface in the same state. When the quota does not apply (disabled,
or an exempt admin), no quota figure SHALL be shown.

#### Scenario: Turns left
- **WHEN** a user with 3 turns left opens the app
- **THEN** the header says 3 turns are left today

#### Scenario: Limit reached
- **WHEN** the user's last turn of the day finishes
- **THEN** the header shows none left and the chat input is disabled with the reason and the local reset time

#### Scenario: Refused by the server
- **WHEN** the chat endpoint answers 429
- **THEN** the interface shows the same disabled state with the reset time from the response and the typed message stays in the input

#### Scenario: Exempt admin
- **WHEN** an exempt admin is signed in
- **THEN** no quota figure is shown and the chat input is enabled
