## MODIFIED Requirements

### Requirement: No secrets in spans
No span or span attribute SHALL contain an API key (the user's OpenAI key or an operator key), a
Logfire write or read token, a key-encryption key, a session or account token, a password, a
connection-string password, or any part of one. Spans SHALL be scrubbed with the same patterns
and protected values as the log redaction.

#### Scenario: Keys stored during a run
- **WHEN** a run uses the user's OpenAI key and the Census and CompTox operator keys
- **THEN** none of the recorded spans contains any of those keys

#### Scenario: Database error in a span
- **WHEN** a span records an exception whose text contains the database URL with its password
- **THEN** the recorded span does not contain the password
