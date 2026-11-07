# api-key-vault Specification

## Purpose

Stores the API keys the assessor needs (the OpenAI key and the Census and CompTox service keys) only in the operating system's credential store, hands them to the model and tools per turn without ever exposing them, and scrubs key-shaped strings from every log.

## Requirements

### Requirement: Keys stored only in the OS credential store
The system SHALL save, read and delete each key (OpenAI, Census, CompTox) only through the OS credential store (macOS Keychain, Linux Secret Service, Windows Credential Locker), under one service name and one account name per key read from configuration (shipped as service `epa-chemical-risk-agent` and accounts `openai_api_key`, `census_api_key` and `comptox_api_key`). It SHALL NOT write a key to `.env` files, configuration, databases, data files, logs, or browser storage, and SHALL NOT keep it in process memory beyond the request that uses it.

#### Scenario: Save
- **WHEN** a key is saved
- **THEN** the credential store is called once with the configured service, that key's account and the key, and nothing else is written

#### Scenario: Keys are independent
- **WHEN** the Census key is saved or cleared
- **THEN** the OpenAI and CompTox entries are unchanged

#### Scenario: Clear
- **WHEN** a key is cleared
- **THEN** the credential store entry for the configured service and that key's account is deleted, and clearing an absent key succeeds

#### Scenario: Credential store unavailable
- **WHEN** no usable credential store backend exists
- **THEN** saving fails with a user-safe message saying the OS keychain is unavailable, and the key is not stored elsewhere

### Requirement: Key validated before storing
The system SHALL accept a key for storage only when it is a non-blank string, has no whitespace or control characters, and is no longer than a configured maximum length. It SHALL NOT call the provider or the service to validate the key.

#### Scenario: Blank key
- **WHEN** an empty or whitespace-only key is submitted
- **THEN** the request is rejected with 422 and the credential store is not called

#### Scenario: Key with embedded newline
- **WHEN** a key containing a newline is submitted
- **THEN** the request is rejected with 422

### Requirement: Key status never reveals the key
Each key (OpenAI, Census and CompTox alike) SHALL have a status endpoint returning only whether it is configured; no part of the key SHALL be returned, not a prefix, a suffix or a masked form. A combined status endpoint SHALL return the three statuses at once. No endpoint, event or error SHALL return a key or any part of it, and the save endpoint SHALL answer with the same status shape.

#### Scenario: Configured
- **WHEN** a status is requested and the key is stored
- **THEN** the response is `{"configured": true}` and contains no character of the stored key

#### Scenario: Not configured
- **WHEN** a status is requested and no key is stored
- **THEN** the response is `{"configured": false}`

#### Scenario: Combined status
- **WHEN** the combined status is requested with only the OpenAI key stored
- **THEN** it reports the OpenAI key as configured and the Census and CompTox keys as not configured

#### Scenario: No GET leaks a key
- **WHEN** every `GET` endpoint is called with all three keys stored
- **THEN** no response body contains any of them

### Requirement: Only the OpenAI key is required to chat
A chat turn SHALL require the OpenAI key and SHALL start without the Census and CompTox keys. A missing service key SHALL be treated as that service being unconfigured: the tools report their own missing-key outcome, and the interface says in Settings which keys are not configured and what each is used for.

#### Scenario: Only the model key stored
- **WHEN** a turn runs with only the OpenAI key stored
- **THEN** the turn starts and a tool that needs the Census or CompTox key reports that key as missing

#### Scenario: No model key
- **WHEN** a turn is submitted with no OpenAI key stored
- **THEN** the turn ends with the missing-key message and no model is built, whatever the other keys

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

### Requirement: Key-shaped strings redacted from logs
The system SHALL install a log filter on the root logger, the web server's loggers and the HTTP client's loggers that replaces every substring matching `sk-[A-Za-z0-9_-]{10,}` with `sk-***REDACTED***` in the formatted message, its arguments, and any attached exception or stack text, before any handler emits it. The filter SHALL never drop a record. The Census and CompTox keys, which have no fixed shape, SHALL additionally be redacted wherever the stored value itself appears in a record during a turn.

#### Scenario: Key in message
- **WHEN** a record's message contains an OpenAI key
- **THEN** the emitted text contains `sk-***REDACTED***` and not the key

#### Scenario: Key in arguments
- **WHEN** a record is logged as `"auth %s"` with the key as its argument
- **THEN** the emitted text is redacted

#### Scenario: Key in exception
- **WHEN** an exception whose message contains a key is logged with its traceback
- **THEN** the emitted traceback text is redacted

#### Scenario: Short `sk-` strings untouched
- **WHEN** a message contains `sk-abc`
- **THEN** it is emitted unchanged

#### Scenario: Service key in a log record
- **WHEN** a turn is running and a record contains the stored Census key
- **THEN** the emitted text does not contain it

### Requirement: Keys reach tools only for the turn
While a turn runs, each key SHALL be available to the tools that need it (the OpenAI key to the SCC embedding lookup, the Census key to the population tool, the CompTox key to the chemical properties tool) through request-scoped holders that exist only for that turn and its concurrent work, so one stored set of keys serves the agent and its tools. The holders SHALL be cleared when the turn ends, SHALL NOT be shared with other turns, and no key SHALL be written to the process environment.

#### Scenario: Tool sees the turn's key
- **WHEN** a tool runs during a turn
- **THEN** it can obtain the key that was read for that turn

#### Scenario: Cleared after the turn
- **WHEN** the turn has ended
- **THEN** the holders are empty and the process environment does not contain the keys

#### Scenario: Concurrent turns
- **WHEN** two threads run turns at the same time under different keys
- **THEN** each turn's tools see only that turn's keys
