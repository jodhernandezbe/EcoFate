## ADDED Requirements

### Requirement: OpenAI key stored per user, encrypted at rest
The web program SHALL store each user's OpenAI key only in the application database,
encrypted with AES-256-GCM under the current key-encryption key, with a fresh random 96-bit
nonce for every encryption and the key's purpose and the owner's user id as associated data.
The database SHALL hold only the nonce, the ciphertext, the identifier of the key-encryption
key that sealed it and timestamps; never the plaintext. Every read, save and clear SHALL act
only on the signed-in user's own row. A ciphertext SHALL decrypt only for the user it was
sealed for. The key-encryption key SHALL come only from the environment variable named in
configuration, SHALL be 32 bytes, and SHALL NOT be stored in the database, configuration
files, logs or responses; the web program SHALL refuse to start when it is missing or
malformed, naming the variable but not its value.

#### Scenario: Save
- **WHEN** a signed-in user saves an OpenAI key
- **THEN** one row for that user holds a nonce and ciphertext from which the key cannot be read without the key-encryption key, and no other user's row changes

#### Scenario: Two saves of the same key
- **WHEN** the same key is saved twice
- **THEN** the two stored nonces and ciphertexts differ

#### Scenario: Row moved to another user
- **WHEN** user A's ciphertext is copied into user B's row and user B starts a turn
- **THEN** decryption fails, user B is treated as having no key, and A's key is never used

#### Scenario: Missing key-encryption key
- **WHEN** the web program starts without the key-encryption key variable set
- **THEN** it exits with a message naming the variable and no server starts

### Requirement: Operator service keys from the environment
The CompTox and Census keys and the Logfire write and read tokens SHALL be the operator's,
read by the server only from the environment variables named in configuration. No endpoint
SHALL accept, store, return or report any part of them; the combined status SHALL report for
each data service only whether it is available on this installation. They SHALL reach the
tools through the per-turn holders like the user's key.

#### Scenario: Census route removed
- **WHEN** a client sends `POST /api/v1/settings/census-key`
- **THEN** the response is 404 and nothing is stored

#### Scenario: Service availability
- **WHEN** the combined status is requested with `COMPTOX_API_KEY` set and `CENSUS_API_KEY` unset
- **THEN** CompTox is reported available and Census unavailable, and no character of either value is returned

### Requirement: Key-encryption key rotation
Each stored ciphertext SHALL record the identifier of the key-encryption key that sealed it.
While a previous key-encryption key is supplied in its configured environment variable, a row
sealed with it SHALL still be readable and SHALL be re-sealed under the current key when read.
A command SHALL re-seal every stored key under the current key-encryption key and report only
counts. A row whose key-encryption key is not available SHALL be reported as unreadable and
treated as not configured, never guessed or deleted silently.

#### Scenario: Rotate
- **WHEN** the operator sets a new current key, keeps the old one as previous and runs the rotation command
- **THEN** every row records the new key's identifier and every user's key still works

#### Scenario: Old key withdrawn too early
- **WHEN** a row was sealed with a key that is neither current nor previous
- **THEN** that user's status reads not configured and the rotation command counts the row as unreadable

### Requirement: Stored key removed with its owner
Clearing the OpenAI key SHALL delete the user's credential row. Deleting an account SHALL
delete every credential row of that user in the same transaction as the account.

#### Scenario: Clear
- **WHEN** a user clears their key
- **THEN** no credential row remains for that user and their status reads not configured

#### Scenario: Account deleted
- **WHEN** an account is deleted
- **THEN** no credential row with that user id remains

### Requirement: No credential in queued work
Any payload the web program hands to a queue or another process SHALL contain identifiers
only (user, thread, turn) and SHALL NOT contain a key, token, password, session cookie or the
key-encryption key. Before a payload is enqueued it SHALL be checked; a payload containing a
key-shaped string, a protected value or a field named like a credential SHALL be refused with
an error and not enqueued.

#### Scenario: Payload with a key
- **WHEN** code tries to enqueue a payload containing the user's OpenAI key
- **THEN** the payload is refused and nothing is enqueued

#### Scenario: Ids only
- **WHEN** a payload with a user id, a thread id and a turn id is enqueued
- **THEN** it passes the check

## MODIFIED Requirements

### Requirement: Key status never reveals the key
The OpenAI key SHALL have a status endpoint returning only whether the signed-in user has one
configured; no part of the key SHALL be returned, not a prefix, a suffix or a masked form. A
combined status endpoint SHALL return the user's OpenAI key status and, for the Census and
CompTox services, only whether each is available on this installation. No endpoint, event or
error SHALL return a key or any part of it, and the save endpoint SHALL answer with the same
status shape.

#### Scenario: Configured
- **WHEN** a status is requested and the user's key is stored
- **THEN** the response is `{"configured": true}` and contains no character of the stored key

#### Scenario: Not configured
- **WHEN** a status is requested and the user has no key stored
- **THEN** the response is `{"configured": false}`

#### Scenario: Another user's key
- **WHEN** user B requests the status while only user A has a key stored
- **THEN** the response is `{"configured": false}`

#### Scenario: Combined status
- **WHEN** the combined status is requested with the user's OpenAI key stored and only the CompTox operator key set
- **THEN** it reports the OpenAI key as configured, CompTox as available and Census as unavailable

#### Scenario: No GET leaks a key
- **WHEN** every `GET` endpoint is called with the user's key stored and every operator key set
- **THEN** no response body contains any of them

### Requirement: Only the OpenAI key is required to chat
A chat turn SHALL require the signed-in user's OpenAI key and SHALL start without the Census
and CompTox operator keys. A missing operator key SHALL be treated as that service being
unavailable on this installation: the tools report their own missing-key outcome, and the
interface says in Settings which data services are unavailable and what each is used for.

#### Scenario: Only the model key stored
- **WHEN** a turn runs with the user's OpenAI key stored and no Census or CompTox operator key set
- **THEN** the turn starts and a tool that needs the Census or CompTox key reports that key as missing

#### Scenario: No model key
- **WHEN** a turn is submitted by a user with no OpenAI key stored
- **THEN** the turn ends with the missing-key message and no model is built, whatever the operator keys

### Requirement: Keys read per request and shared by every call
For each chat turn the system SHALL decrypt the signed-in user's OpenAI key once, in the
process that runs the turn, wrap it as a secret value, and use the same value for every model
call of the turn (the scope classifier and the agent); the operator keys SHALL be read from
the environment. The command-line program SHALL keep using the keys stored in the OS
credential store, falling back to the configured environment variable for each key the
credential store does not hold; the web program SHALL NOT use the OS credential store.

#### Scenario: One read per key per turn
- **WHEN** a turn makes a classifier call and three agent model calls
- **THEN** the user's key is decrypted once and all four calls use it

#### Scenario: Key changed between turns
- **WHEN** a user replaces their key in Settings between two turns
- **THEN** the second turn uses the new key without restarting the program

#### Scenario: CLI with stored key
- **WHEN** the command-line program runs with a stored key and the environment variable set
- **THEN** the stored key is used

#### Scenario: CLI without stored key
- **WHEN** the command-line program runs with no stored key and the environment variable set
- **THEN** the environment variable's key is used

#### Scenario: Container web program
- **WHEN** the web program runs with the container flag, the OpenAI environment variable is set and the signed-in user has stored no key
- **THEN** the turn ends with the add-your-key message, the environment's OpenAI key is not used, and the Census and CompTox keys still come from the environment

### Requirement: Key-shaped strings redacted from logs
The system SHALL install a log filter on the root logger, the web server's loggers and the HTTP
client's loggers that, in the formatted message, its arguments, and any attached exception or
stack text, before any handler emits it: replaces every substring matching
`sk-[A-Za-z0-9_-]{10,}` with `sk-***REDACTED***`; replaces the values of `Cookie` and
`Set-Cookie` headers (session tokens) and of `token=` in URL fragments (verification and reset
tokens); and replaces bearer, query-string and assignment-style credentials as before. The
filter SHALL never drop a record. Values with no fixed shape SHALL be redacted wherever the
exact value appears: the user's OpenAI key and the operator keys during a turn, and for the
life of the process the key-encryption keys, the session secret, the SMTP password, the
operator keys and the Logfire tokens.

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
- **WHEN** a turn is running and a record contains the Census operator key
- **THEN** the emitted text does not contain it

#### Scenario: Reset link in a record
- **WHEN** a record contains `https://ecofate.example/reset#token=Zx81kLmq0PaT3vYb`
- **THEN** the emitted text keeps the address and does not contain the token

#### Scenario: Fragment without a token untouched
- **WHEN** a record contains `https://example.org/docs#usage`
- **THEN** it is emitted unchanged

#### Scenario: Key-encryption key in a record
- **WHEN** any record contains the key-encryption key's value
- **THEN** the emitted text does not contain it

#### Scenario: Session cookie header
- **WHEN** a record contains a `Cookie:` header with a session token
- **THEN** the emitted text does not contain the token

### Requirement: Keys reach tools only for the turn
While a turn runs, each key SHALL be available to the tools that need it (the user's OpenAI
key to the SCC embedding lookup, the operator's Census key to the population tool, the
operator's CompTox key to the chemical properties tool) through request-scoped holders that
exist only for that turn and its concurrent work. The holders SHALL be cleared when the turn
ends, SHALL NOT be shared with other turns, and no key SHALL be written to the process
environment.

#### Scenario: Tool sees the turn's key
- **WHEN** a tool runs during a turn
- **THEN** it can obtain the key that was read for that turn

#### Scenario: Cleared after the turn
- **WHEN** the turn has ended
- **THEN** the holders are empty and the process environment does not contain the user's key

#### Scenario: Concurrent turns
- **WHEN** two users run turns at the same time with their own OpenAI keys
- **THEN** each turn's model calls and tools see only that user's key

## REMOVED Requirements

### Requirement: Keys stored only in the OS credential store
**Reason**: The web program serves many users from a container with no OS credential store;
each user's OpenAI key is now stored encrypted per user in the application database, and the
service keys are the operator's environment variables.
**Migration**: The command-line program keeps using the OS credential store (unchanged
`app/key_vault.py`). Web users save their OpenAI key again in Settings after signing in; the
operator sets `COMPTOX_API_KEY` and `CENSUS_API_KEY` in the server environment.
