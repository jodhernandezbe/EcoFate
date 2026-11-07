## ADDED Requirements

### Requirement: Database settings
The system SHALL read from a `[database]` table, validated on load: the name of the
environment variable holding the connection URL (never the URL itself), the connection pool
size, the pool and statement timeouts and the health-check timeout (seconds), the turn lease
(seconds, greater than the agent timeout), the idle-thread retention (days) and the purge
interval (minutes). Every number SHALL be positive and not a boolean.

#### Scenario: Settings loaded
- **WHEN** the database settings are loaded
- **THEN** they expose the variable name `DATABASE_URL` and the configured numbers, and no URL

#### Scenario: Invalid entry
- **WHEN** a timeout, pool size, retention or interval is zero, negative or a boolean, the variable name is empty, or the turn lease is not greater than `[agent].timeout_seconds`
- **THEN** the loader raises a `ValueError` naming the offending key

## MODIFIED Requirements

### Requirement: Web UI settings
The system SHALL read from a `[ui]` table, validated on load, and SHALL NOT embed these values
in Python or frontend code:
- the server host (loopback only) and port, and the built-frontend directory;
- the credential-store service name, the account name of each key (OpenAI, Census, CompTox) and the maximum accepted key length;
- the names of the scope classifier and scope addendum prompts, the fallback redirect prompt,
  and how many earlier messages the classifier sees;
- the names of the completion reviewer and nudge prompts, and the most nudges per user turn (a
  non-negative integer; zero turns the completion check off);
- the step label per tool name;
- the light and dark basemap style URLs, the initial map view (the bounds of the contiguous
  United States), the downwind sector half-angle (degrees), the marker size scale for emission
  rate, and the coordinate tolerance for matching receptors to facilities;
- the HQ threshold of concern and the lower bound of the "near" band, and the cancer-risk
  thresholds, each with a comment naming its basis;
- the suggestion chip texts, the significant digits for metrics, and the narrow-viewport
  breakpoint;
- the workspace layout limits: the collapsed rail width (px), the expanded rail's default,
  minimum and maximum width (px), the chat dock's default share of the viewport, its minimum
  width (px) and maximum share of the viewport, and the overview panel's default, minimum and
  maximum share of the analysis area;
- per-model token prices (USD per million input, cached input and output tokens) with the date
  and source they were taken from.
Thread retention is a database setting, not a UI setting; a `[ui]` table that still sets the
removed in-memory thread maximum SHALL be rejected with a message naming the database
retention key.
The frontend SHALL receive the display and layout settings it needs from an API endpoint, never
by duplicating them.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the UI settings
- **THEN** it returns the values from the file

#### Scenario: Invalid entry
- **WHEN** the port is out of range, the host is not a loopback address, a threshold or price is negative or a boolean, the "near" lower bound exceeds the threshold of concern, a prompt name is empty, or the nudge limit is negative or a boolean
- **THEN** the loader raises a `ValueError` naming the offending key

#### Scenario: Invalid layout limits
- **WHEN** a layout minimum exceeds its maximum, a default lies outside its limits, a share is not strictly between 0 and 1, or a width is not a positive integer
- **THEN** the loader raises a `ValueError` naming the offending key

#### Scenario: Removed thread maximum
- **WHEN** the `[ui]` table sets `max_threads`
- **THEN** the loader raises a `ValueError` naming `database.thread_retention_days`

#### Scenario: Completion check off
- **WHEN** `max_nudges` is 0
- **THEN** the program builds the agent without the completion check

#### Scenario: Frontend reads display settings
- **WHEN** the frontend starts
- **THEN** it fetches thresholds, map styles, the initial view, layout limits, chips and digits from the API instead of hard-coding them
