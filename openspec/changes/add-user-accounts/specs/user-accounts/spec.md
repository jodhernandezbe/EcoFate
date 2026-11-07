## ADDED Requirements

### Requirement: Sign up with email and password
The system SHALL let a person create an account with an email address and a password when
sign-up is open in configuration. The email SHALL be validated and normalised (trimmed,
domain lower-cased) and SHALL be unique. The password SHALL be between the configured minimum
and maximum length and SHALL NOT equal the email; no other composition rule SHALL be imposed.
The password SHALL be stored only as an Argon2id hash with parameters from configuration. A
new account SHALL be unverified and have the `user` role. The response SHALL be the same
status and body whether or not the email already had an account; when it did, no second
account is created and the existing owner is emailed instead.

#### Scenario: New account
- **WHEN** a person signs up with an unused email and a valid password
- **THEN** an unverified `user` account is created, the stored password is an Argon2id hash, and a verification email is sent

#### Scenario: Email already registered
- **WHEN** a person signs up with an email that already has an account
- **THEN** the response status and body equal those of a new sign-up, no account is created, and the password of the existing account is unchanged

#### Scenario: Password too short
- **WHEN** the password is shorter than the configured minimum
- **THEN** the request is rejected with 422 naming the field and no account is created

#### Scenario: Sign-up closed
- **WHEN** sign-up is closed in configuration
- **THEN** the sign-up endpoint answers 403 with a user-safe message and no account is created

### Requirement: Email verification
The system SHALL email a verification link carrying a random single-use token. Only the
token's hash SHALL be stored, with an expiry from configuration. Consuming a valid token SHALL
mark the account verified and the token used, atomically, so it cannot be used twice. A newer
token for the same account and purpose SHALL invalidate older ones. Resending verification
SHALL answer identically for known, unknown and already verified emails.

#### Scenario: Verify
- **WHEN** the link's token is submitted before it expires
- **THEN** the account becomes verified and the token cannot be used again

#### Scenario: Expired token
- **WHEN** a token is submitted after its expiry
- **THEN** the request is rejected with a user-safe message and the account stays unverified

#### Scenario: Token reused
- **WHEN** an already used token is submitted
- **THEN** the request is rejected and nothing changes

### Requirement: Sign in and server-side sessions
Signing in with a verified account's correct email and password SHALL create a session: a
random token of at least 256 bits set in a cookie that is `HttpOnly`, `SameSite=Lax`, `Path=/`
and `Secure` (unless configuration disables `Secure` for a non-production environment), with
only its hash stored server-side together with the user, an idle expiry and an absolute expiry
from configuration. Any session cookie the browser sent before signing in SHALL be replaced.
A wrong password and an unknown email SHALL produce the same response, and an unknown email
SHALL still cost one password-hash verification. A correct password on an unverified account
SHALL return a `verification_required` state and no session. Signing out SHALL delete the
session server-side and clear the cookie.

#### Scenario: Successful sign in
- **WHEN** a verified user signs in with the right password
- **THEN** a session cookie with the required flags is set and only the token's hash is stored

#### Scenario: Wrong password and unknown email look alike
- **WHEN** one sign-in uses a wrong password and another an email with no account
- **THEN** both responses have the same status and body

#### Scenario: Unverified account
- **WHEN** an unverified account signs in with the right password
- **THEN** the response says verification is required and no session is created

#### Scenario: Expired session
- **WHEN** a request carries a session past its idle or absolute expiry
- **THEN** it is answered 401 and the session row is deleted

#### Scenario: Sign out
- **WHEN** a user signs out
- **THEN** the session row is deleted and a later request with the old cookie is answered 401

#### Scenario: Stolen database row
- **WHEN** a stored session hash is presented as a cookie value
- **THEN** it is not accepted as a session

### Requirement: Password recovery
Requesting recovery for an email SHALL always answer with the same status and body. When the
email belongs to an account, a single-use reset token SHALL be emailed in a link that carries
it outside the query string (the URL fragment), stored only as a hash, expiring after the
configured time. Submitting a valid token with a new valid password SHALL set the new hash,
mark the token used, invalidate every other reset token of the account, and delete all of the
account's sessions. Recovery requests SHALL be throttled like sign-in attempts.

#### Scenario: Known email
- **WHEN** recovery is requested for a registered email
- **THEN** a reset email is sent and the response equals the one for an unknown email

#### Scenario: Reset password
- **WHEN** a valid reset token and a new valid password are submitted
- **THEN** the password changes, the token cannot be reused and every existing session of the account is revoked

#### Scenario: Expired reset token
- **WHEN** a reset token is submitted after its expiry
- **THEN** the password does not change

### Requirement: Login throttling
Failed sign-in and recovery attempts SHALL be counted per normalised email and per client
address within a configured window. Past the configured limit the endpoint SHALL answer 429
with a `Retry-After` header and SHALL NOT check the password or reveal whether it was right.
The client address SHALL be the socket peer, or the configured number of trusted proxy hops
from `X-Forwarded-For` when configuration says a proxy is in front.

#### Scenario: Too many failures for one email
- **WHEN** sign-in fails the configured number of times for one email within the window
- **THEN** the next attempt for that email is answered 429 even with the right password

#### Scenario: Spoofed forwarded header
- **WHEN** no trusted proxy is configured and a request carries `X-Forwarded-For`
- **THEN** the header is ignored and the socket address is counted

### Requirement: Roles and the create-admin command
Every account SHALL have exactly one role, `user` or `admin`. The system SHALL NOT ship a
default admin account or password. A command-line subcommand of the web program SHALL create a
verified admin account for an email, or promote an existing account, reading the password from
a hidden interactive prompt (or from standard input only when an explicit flag says so); the
password SHALL NOT be accepted as a command-line argument or environment variable.

#### Scenario: First admin
- **WHEN** the operator runs the create-admin command with a new email and enters a valid password
- **THEN** a verified `admin` account exists and the password does not appear in the process arguments or output

#### Scenario: Promote
- **WHEN** the command runs for an email that already has a `user` account
- **THEN** the account becomes `admin` and keeps its password unless a new one is entered

### Requirement: Account management
A signed-in user SHALL be able to change their password (giving the current one), sign out of
every session, and delete their account (giving their password). Changing the password SHALL
revoke every other session. Deleting the account SHALL delete the user's sessions, tokens,
threads, checkpoints, workspaces, usage records and any stored credentials, and SHALL sign the
user out.

#### Scenario: Change password
- **WHEN** a user changes their password with the right current password
- **THEN** the new password works, the old one does not, and the user's other sessions are revoked

#### Scenario: Delete account
- **WHEN** a user deletes their account with the right password
- **THEN** no row referring to the user remains in any table and their cookie is answered 401

### Requirement: Authentication secrets stay out of every output
Passwords, session tokens, verification tokens and reset tokens SHALL NOT appear in any
response body (other than the cookie header that sets a session), event, log record, span,
error message or URL query string. Authentication settings SHALL come from configuration and
secrets (the session secret, the SMTP password) only from environment variables named in
configuration.

#### Scenario: Sign-in logged
- **WHEN** a sign-in request is processed with logging at debug level
- **THEN** no log record contains the submitted password or the session token

#### Scenario: Reset link in access logs
- **WHEN** a user follows a reset link
- **THEN** the server access log does not contain the reset token
