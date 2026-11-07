## MODIFIED Requirements

### Requirement: Single-command local launch
The system SHALL start the web program with one command that serves both the API and the
built frontend from the same origin. It SHALL bind only to the loopback interface on the host
and port read from configuration, and SHALL refuse to start with a clear message when the
built frontend is missing. With the container flag, it SHALL instead bind to the container
bind address read from configuration (a loopback or the unspecified address), on the same
port; the flag SHALL NOT change the host and port used as the program's origin.

#### Scenario: Launch
- **WHEN** the user runs the launch command after building the frontend
- **THEN** the interface is served at the configured loopback address and the API answers under `/api`

#### Scenario: Frontend not built
- **WHEN** the launch command runs and the built frontend directory does not exist
- **THEN** the program exits with a message naming the build command, and no server starts

#### Scenario: Non-loopback host configured
- **WHEN** the configured host is not a loopback address
- **THEN** loading the configuration raises an error naming the host key

#### Scenario: Container launch
- **WHEN** the launch command runs with the container flag
- **THEN** the server listens on the configured container bind address and port, and the origin checks still use the configured host and port

### Requirement: Cross-site requests are rejected
Every state-changing endpoint (chat turns, saving or clearing the key, resetting a thread)
SHALL reject requests whose `Origin` (or, without one, `Referer`) is not the program's own
origin, and every endpoint SHALL reject requests whose `Host` is not the configured host and
port, whatever address the server is bound to, so a third-party web page cannot spend tokens
or change the key.

#### Scenario: Foreign origin
- **WHEN** a `POST` to the chat endpoint carries `Origin: https://example.com`
- **THEN** the response is 403 and the agent is not run

#### Scenario: Same origin
- **WHEN** a `POST` carries the program's own origin
- **THEN** the request is processed

#### Scenario: DNS-rebinding host
- **WHEN** a request arrives with a `Host` header other than the configured host and port
- **THEN** the response is 403

#### Scenario: Container bind does not widen the host check
- **WHEN** the server runs with the container flag and a request carries `Host: 0.0.0.0:8000`
- **THEN** the response is 403
