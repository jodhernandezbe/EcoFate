## MODIFIED Requirements

### Requirement: Only the OpenAI key is required to chat
A chat turn SHALL require the signed-in user's OpenAI key and SHALL start without the Census
and CompTox operator keys. A missing operator key SHALL be treated as that service being
unavailable on this installation: the tools report their own missing-key outcome in the answer.
The operator keys are the operator's concern only; the interface SHALL NOT ask users about them
or list them in Settings.

#### Scenario: Only the model key stored
- **WHEN** a turn runs with the user's OpenAI key stored and no Census or CompTox operator key set
- **THEN** the turn starts and a tool that needs the Census or CompTox key reports that key as missing

#### Scenario: No model key
- **WHEN** a turn is submitted by a user with no OpenAI key stored
- **THEN** the turn ends with the missing-key message and no model is built, whatever the operator keys
