## ADDED Requirements

### Requirement: Spans carry an opaque user id
Each web turn's session span SHALL carry the signed-in user's id under the attribute name
configured in the telemetry settings. The id SHALL be the account's random identifier, never
the email, the password hash or anything derived from them. Command-line runs SHALL carry no
user id.

#### Scenario: Web turn
- **WHEN** a signed-in user runs a turn with telemetry enabled
- **THEN** the turn's session span has the user id attribute set to that user's id and contains no email

#### Scenario: Command-line run
- **WHEN** the command-line program runs
- **THEN** its session span has no user id attribute
