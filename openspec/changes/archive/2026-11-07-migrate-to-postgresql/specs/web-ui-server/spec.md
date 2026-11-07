## MODIFIED Requirements

### Requirement: Conversation threads
The program SHALL keep each thread's message history, dashboard state and session usage in
the database, so follow-up turns see earlier turns, also after the program restarts or when
another process serves the next turn. Clearing the workspace in the UI SHALL reset the thread
it shows. The program SHALL delete threads that have been idle longer than the configured
retention period; a thread running a turn SHALL NOT be deleted. A thread SHALL be resettable,
and only one turn per thread SHALL run at a time, across every process that serves the
program.

#### Scenario: Follow-up turn
- **WHEN** a second turn is sent on the same thread
- **THEN** the agent receives the first turn's messages and the dashboard keeps the earlier facilities

#### Scenario: Follow-up after a restart
- **WHEN** the program restarts between the first and the second turn of a thread
- **THEN** the agent receives the first turn's messages and the dashboard keeps the earlier facilities

#### Scenario: Reset
- **WHEN** the thread is reset
- **THEN** its history, dashboard and session usage are cleared

#### Scenario: Reset during a turn
- **WHEN** a reset is requested while the thread is running a turn
- **THEN** the request is answered 409 and the running turn is unaffected

#### Scenario: Concurrent turn on one thread
- **WHEN** a turn is submitted while another turn of the same thread is still running
- **THEN** the second request is answered 409 and the running turn is unaffected

#### Scenario: Retention limit
- **WHEN** a thread has been idle longer than the configured retention period
- **THEN** it is deleted with its history, dashboard and usage, and a later snapshot request for it is answered 404

#### Scenario: Running thread not evicted
- **WHEN** a thread older than the retention period is running a turn at purge time
- **THEN** it is not deleted
