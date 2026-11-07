## ADDED Requirements

### Requirement: Authenticated API
Every API route SHALL require a valid session except: the health check, the static frontend,
the client display settings, and the public authentication routes (sign up, verify, resend
verification, sign in, forgot password, reset password). A request without a valid session
SHALL be answered 401 with a generic message and a correlation id, before any handler logic,
agent call or database write. `GET /api/v1/auth/me` SHALL return the signed-in user's id,
email, role and verification state, and 401 otherwise. The origin guard SHALL keep running in
front of every route, including the public authentication routes.

#### Scenario: Chat without a session
- **WHEN** a `POST` to the chat-stream endpoint carries no session cookie
- **THEN** the response is 401 and the agent is not run

#### Scenario: Public route
- **WHEN** an anonymous client posts to the sign-in route from the app's own origin
- **THEN** the request is processed

#### Scenario: Public route from a foreign origin
- **WHEN** an anonymous client posts to the sign-in route with a foreign `Origin`
- **THEN** the response is 403

#### Scenario: Who am I
- **WHEN** a signed-in admin calls `GET /api/v1/auth/me`
- **THEN** the response contains their id, email and role `admin` and no session token
