# monitoring-dashboard Specification

## Purpose
Shows recorded agent sessions inside the app. The Monitoring view lists recent sessions with
their token usage and cost, and shows one session's model and tool calls in order. Its data is
read back from the monitoring platform (Logfire) and never estimated or invented.

## Requirements

### Requirement: Sessions read from the monitoring platform
The server SHALL offer a read-only endpoint listing recent sessions, newest first. The number
listed and the time window are capped by configuration. Each session is a group of turn or
command-line spans sharing a session id, and is listed with: start time, first question, model,
number of turns, model calls, tool calls, input, cached input and output tokens, estimated cost
and cost status, total duration and outcome. Each figure SHALL come from the recorded spans:
counts are counted from the trace, and tokens and cost are read from the attributes the
telemetry wrote. A figure missing from the trace SHALL be returned as absent, never as zero.
Each listing SHALL make one bounded query to the Logfire query API, authenticated with the
Logfire read token and limited by the configured timeout.

#### Scenario: Recent sessions
- **WHEN** three sessions were recorded in the window and the read token is set
- **THEN** the endpoint returns those three, newest first, each with its counts, tokens and cost

#### Scenario: Missing usage attribute
- **WHEN** a session's span has no cost attribute
- **THEN** that session's cost is returned as absent and its status as unknown

### Requirement: Session timeline
The server SHALL offer a read-only endpoint returning one session's turns. For each turn it
SHALL return the model calls and tool calls in start order, each with its kind (model or tool),
its name (the model name, or the tool's configured step label), start offset, duration, outcome
and, for model calls, token usage. It SHALL also return a link that opens the trace in Logfire,
built from the configured URL template and the project the read token belongs to. The session
id SHALL be validated before it is used in a query, and an unknown id SHALL return 404.

#### Scenario: Open a session
- **WHEN** a session with two turns is requested
- **THEN** both turns are returned with their model and tool calls in order and a Logfire link per turn

#### Scenario: Malformed id
- **WHEN** the session id contains characters outside the allowed set
- **THEN** the request is rejected with 422 and no query is made

### Requirement: Read token from the environment, never exposed
The Logfire read token SHALL be read from the environment variable named in configuration
(shipped as `LOGFIRE_READ_TOKEN`, normally set in the project's gitignored `.env`). The user
SHALL NOT be asked to enter it in the interface. The token SHALL be used only to query the
Logfire query API. It SHALL NOT be given to the agent, the tools or the chat model, SHALL NOT be
needed to chat or to send traces, and SHALL NOT appear in any response, event, error, log or
span; it is added to the log redaction like the other environment keys.

#### Scenario: Chat without a read token
- **WHEN** a chat turn runs with no read token set
- **THEN** the turn runs normally and its trace is still recorded

#### Scenario: Token never returned
- **WHEN** every monitoring endpoint is called with the read token set, including on a Logfire error
- **THEN** no response body and no log record contains the token

### Requirement: Clear states when monitoring is unavailable
The monitoring endpoints SHALL return a distinct, user-safe state instead of data when no read
token is set (`not_configured`), when Logfire cannot be reached, times out or rate-limits
(`unavailable`), or when Logfire refuses the token (`unauthorized`). They SHALL NOT return
cached or invented sessions in these states. Error details SHALL go only to the server log,
redacted.

#### Scenario: No read token
- **WHEN** the sessions are requested with no Logfire read token set
- **THEN** the response state is `not_configured` and Logfire is not called

#### Scenario: Logfire down
- **WHEN** the Logfire query API times out
- **THEN** the response state is `unavailable` with a user-safe message and no sessions

### Requirement: Monitoring view
Activating "Monitoring" in the navigation rail SHALL show the Monitoring view in the analysis
area, in place of the workspace panels. The panels SHALL stay mounted and unchanged, and
activating "Workspace" returns to them. The view SHALL show a sessions table with the listed
fields, using the dashboard's number, unit and cost formatting, with cost labelled as an
estimate. It SHALL have a refresh action. Selecting a session SHALL show its timeline: each turn's
model and tool calls as rows, with name, duration bar, tokens and outcome, plus an "Open in
Logfire" link that opens in a new tab. In the `not_configured` state the view SHALL say that
monitoring is not set up for this installation (the read token is missing from the server's
environment) and that runs are still recorded; it SHALL NOT ask for the token. In the `unavailable` and `unauthorized`
states it SHALL show the message and a retry action. While loading it SHALL show a progress
state, never an empty table presented as "no sessions".

#### Scenario: Browse sessions
- **WHEN** the user opens Monitoring with the read token set and sessions recorded
- **THEN** the sessions table lists them with tokens and estimated cost, and selecting one shows its model and tool calls in order

#### Scenario: Not configured
- **WHEN** the user opens Monitoring and the server has no read token set
- **THEN** the view says monitoring is not set up and shows no input asking for the token

#### Scenario: Back to the workspace
- **WHEN** the user is on Monitoring and activates "Workspace"
- **THEN** the overview, map and chat are shown again exactly as they were left

#### Scenario: No sessions yet
- **WHEN** Logfire returns no sessions in the window
- **THEN** the view says no sessions were recorded in that window and how to start one

### Requirement: Sessions table fits its pane
The sessions table SHALL never be wider than the analysis area. Started, question, estimated
cost and status SHALL always be visible; model and turns SHALL appear on a medium pane; model
calls, tool calls, tokens and duration SHALL appear only on a wide pane. A question longer than
its column SHALL be truncated with the whole question available as its tooltip. Every column
header SHALL be distinct.

#### Scenario: Narrow analysis area
- **WHEN** the analysis area is narrow (a 1280 px window with the chat open)
- **THEN** started, question, estimated cost and status are visible and nothing scrolls horizontally

#### Scenario: Medium analysis area
- **WHEN** the analysis area is medium (a 1920 px window with the chat open)
- **THEN** model and turns are visible too and nothing scrolls horizontally

#### Scenario: Wide analysis area
- **WHEN** the analysis area is wide enough for every column
- **THEN** every column is visible

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
