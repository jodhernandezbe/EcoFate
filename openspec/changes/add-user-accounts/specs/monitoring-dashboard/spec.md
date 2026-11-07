## ADDED Requirements

### Requirement: Monitoring only for administrators
The monitoring endpoints SHALL be available only to signed-in users with the `admin` role.
For any other signed-in user they SHALL answer 404 with the same body as an unknown route, and
SHALL NOT query Logfire. Each listed session SHALL show the account that ran it, resolved from
the opaque user id recorded on its spans to an email through the application database; a
session whose user id is absent or unknown SHALL show the account as absent. Emails SHALL NOT
be read from or sent to the monitoring platform.

#### Scenario: Non-admin calls the endpoint
- **WHEN** a signed-in `user` requests the sessions listing
- **THEN** the response is 404 and no Logfire query is made

#### Scenario: Admin sees the account
- **WHEN** an admin lists sessions recorded by two different users
- **THEN** each session shows the email of the user who ran it

#### Scenario: Deleted account
- **WHEN** a listed session was run by an account that has since been deleted
- **THEN** its account is shown as absent and the rest of the row is unchanged
