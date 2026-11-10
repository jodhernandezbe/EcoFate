# tenant-isolation Specification

## Purpose

Per-user ownership of every stored and in-memory artefact of a conversation: each thread and
everything kept for it belongs to one user, a thread of another user is answered exactly like
an unknown one, and concurrent turns of different users cannot see or release each other's state.

## Requirements

### Requirement: Every conversation artefact has one owner
Every thread SHALL belong to the user who started it, recorded when its first turn is
accepted. Its turn records, message history and checkpoints, workspace state, session usage,
pending confirmation, supplied and declined values, and generated report SHALL be stored and looked up
only together with that owner. The ownership check SHALL live in the storage layer: every
repository operation on these artefacts SHALL require the owner's id and include it in its
query. Two users using the same thread identifier SHALL get two separate threads, and their
checkpoints SHALL NOT share a checkpointer thread key.

#### Scenario: Same thread id, two users
- **WHEN** user A and user B each send a turn with thread id `t1`
- **THEN** each sees only their own messages and workspace for `t1`

#### Scenario: Repository without an owner
- **WHEN** a repository method for a thread artefact is called without an owner id
- **THEN** it fails type checking, and no such method exists in the storage layer

### Requirement: Foreign ids look like unknown ids
A request naming a thread that belongs to another user SHALL be answered exactly as a request
naming a thread that does not exist: the same status (404), the same body, and no side
effect. This SHALL hold for the thread snapshot, the report, the reset, the chat-stream
endpoint when it would resume or answer a confirmation, and any other route taking a thread
id.

#### Scenario: Read another user's thread
- **WHEN** user B requests the snapshot of user A's thread
- **THEN** the response is 404 with the same body as for an unknown thread

#### Scenario: Reset another user's thread
- **WHEN** user B sends `DELETE` for user A's thread
- **THEN** the response is 404 and user A's thread is unchanged

#### Scenario: Report of another user's thread
- **WHEN** user B requests the report of user A's thread
- **THEN** the response is 404 and no document is built

### Requirement: In-memory turn state isolated per user
State that identifies a running turn (the active-turn record, the live workspace held in
memory, the pending confirmation, the per-turn credentials) SHALL be keyed by owner and
thread, with the owner taken from the authenticated session and never from the request body.
One user's turn SHALL NOT be able to claim, release, read or reset another user's in-memory
state. Per-turn credentials SHALL stay in context-local holders. No module-level mutable
object in the web backend SHALL hold user data.

#### Scenario: Concurrent turns of two users on the same thread id
- **WHEN** users A and B run turns on thread id `t1` at the same time
- **THEN** neither is answered 409, and each turn's events contain only its own workspace

#### Scenario: Release by another user
- **WHEN** user B's request ends while user A's turn on the same thread id is running
- **THEN** user A's thread stays marked as running

#### Scenario: Module-level state scan
- **WHEN** the test suite scans the web backend for module-level mutable assignments
- **THEN** none is found outside the reviewed allow-list of constants
