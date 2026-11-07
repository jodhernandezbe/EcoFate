## ADDED Requirements

### Requirement: Container bind address setting
The system SHALL read from a `[ui.container]` table the address the web program listens on
when launched with the container flag (`bind_host`), validated on load as a loopback address
or the unspecified address (`0.0.0.0` or `::`). The value SHALL NOT be read from the
environment or embedded in Python code.

#### Scenario: Setting loaded
- **WHEN** the UI settings are loaded
- **THEN** they expose the container bind address from the file

#### Scenario: Public address refused
- **WHEN** `bind_host` is a routable address such as `203.0.113.5`, an empty string or not a string
- **THEN** the loader raises a `ValueError` naming `ui.container.bind_host`
