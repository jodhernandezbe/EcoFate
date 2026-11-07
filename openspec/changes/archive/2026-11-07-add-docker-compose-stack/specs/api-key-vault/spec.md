## MODIFIED Requirements

### Requirement: Keys read per request and shared by every call
For each chat turn the system SHALL read each stored key from the credential store once, wrap it as a secret value, and use the same OpenAI value for every model call of the turn (the scope classifier and the agent). The command-line program SHALL use the same stored keys, falling back to the configured environment variable for each key the credential store does not hold. The web program launched with the container flag (where no credential store exists) SHALL instead read each key from its configured environment variable once per turn, in the same way.

#### Scenario: One read per key per turn
- **WHEN** a turn makes a classifier call and three agent model calls
- **THEN** the credential store is read once for the OpenAI key and all four calls use it

#### Scenario: Key changed between turns
- **WHEN** a key is replaced in Settings between two turns
- **THEN** the second turn uses the new key without restarting the program

#### Scenario: CLI with stored key
- **WHEN** the command-line program runs with a stored key and the environment variable set
- **THEN** the stored key is used

#### Scenario: CLI without stored key
- **WHEN** the command-line program runs with no stored key and the environment variable set
- **THEN** the environment variable's key is used

#### Scenario: Container web program
- **WHEN** the web program runs with the container flag and the OpenAI environment variable is set
- **THEN** each turn uses that variable's key and the credential store is never called
