# app-configuration Specification

## Purpose

Keeps external-service URLs, endpoints and timing parameters in a configuration file
so they can change without editing code.

## Requirements

### Requirement: Externalized service settings
The system SHALL read the CompTox base URL, endpoint path templates (CAS search, chemical detail, property summary and ToxVal), request delay and request timeout from a configuration file, and SHALL NOT embed them in Python code. The configuration SHALL also name the CompTox API-key header and the environment variable holding the key, SHALL name where molecular weight is read from (response field, the unit the service reports it in, target unit), SHALL list the CompTox properties to extract (CompTox property name, result key, target unit), and SHALL list the CompTox toxicity values to extract (result key, accepted ToxVal type labels, accepted exposure routes, preference for the lowest or highest value, target unit) together with the ordered source-priority list used to choose among records. The configuration SHALL also hold a table of unit-spelling aliases used before unit conversion.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the CompTox settings
- **THEN** it returns the base URL, endpoint templates, delay and timeout from the file, plus the header name, key variable name, property list, toxicity value list and source-priority list for CompTox, with a target unit on every property and toxicity entry and routes and preference on every toxicity entry

#### Scenario: Changing the endpoint
- **WHEN** the URL in the configuration file is edited
- **THEN** subsequent lookups use the new URL with no code change

#### Scenario: Adding a property
- **WHEN** an entry is added to the CompTox property list
- **THEN** the loader returns it with no code change

#### Scenario: Adding a toxicity value
- **WHEN** an entry is added to the CompTox toxicity value list
- **THEN** the loader returns it with no code change

#### Scenario: Invalid toxicity entry
- **WHEN** a toxicity entry has no key, no accepted labels, no accepted routes, a preference other than "lowest" or "highest", or a duplicate key
- **THEN** the loader raises a `ValueError` naming the offending key

#### Scenario: Molecular weight settings
- **WHEN** the loader is asked for the CompTox settings
- **THEN** it returns the molecular weight response field, reported unit and target unit, and raises a `ValueError` naming the key if the table or any of its keys is missing

#### Scenario: Missing target unit
- **WHEN** a property or toxicity entry has no target unit
- **THEN** the loader raises a `ValueError` naming the offending key

#### Scenario: CAS search path without placeholder
- **WHEN** the CAS search path does not contain the CAS placeholder
- **THEN** the loader raises a `ValueError` naming the key

#### Scenario: Unit aliases loaded
- **WHEN** the loader is asked for the unit settings
- **THEN** it returns the alias table from the file, and a missing table yields no aliases

### Requirement: Validated, typed configuration
The system SHALL validate the configuration on load and expose it as typed objects.

#### Scenario: Missing or invalid value
- **WHEN** a required key is missing, or the delay or timeout is negative or non-numeric
- **THEN** the loader raises a `ValueError` naming the offending key

#### Scenario: Missing file
- **WHEN** the configuration file does not exist
- **THEN** the loader raises `FileNotFoundError` naming the path

### Requirement: Overridable location
The system SHALL allow the configuration file path to be supplied explicitly, and
otherwise use the default file shipped in the repository.

#### Scenario: Explicit path
- **WHEN** a path is passed to the loader
- **THEN** that file is read instead of the default

### Requirement: Secrets kept out of configuration
The configuration file SHALL NOT contain API keys; it SHALL only name the environment variable that holds them.

#### Scenario: Key reference
- **WHEN** CompTox settings are loaded
- **THEN** they expose the environment variable name, not a key value

### Requirement: Externalized TRI settings
The system SHALL read the EPA Envirofacts TRI release-query path template, page size, maximum pages, and the list of environmental media to keep from the configuration file, and SHALL NOT embed them in Python code; the base URL, delay between requests, request timeout, maximum retries and retry backoff come from the shared `[efservice]` table. The configuration SHALL also name the TRI field names used for the kept records so a renamed column needs only a configuration change, and the list of states whose longitudes are east of Greenwich. The configuration SHALL also hold the operating hours per year used to turn an annual release into a rate (an `[emissions]` table, default 8,760), validated on load.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the TRI settings
- **THEN** it returns the path template, paging values and the media list from the file

#### Scenario: Changing the media
- **WHEN** a medium is added to or removed from the configured list
- **THEN** subsequent lookups use the new list with no code change

#### Scenario: Operating hours loaded
- **WHEN** the loader is asked for the emissions settings
- **THEN** it returns the operating hours per year from the file, and the unit alias table includes the TRI mass spelling "Pounds"

#### Scenario: Invalid operating hours
- **WHEN** the operating hours per year are missing, non-numeric, a boolean, zero, negative, or greater than 8,784
- **THEN** the loader raises a `ValueError` naming the key

#### Scenario: Invalid value
- **WHEN** the page size or page cap is not a positive integer, the media list is empty, or the path lacks the CAS placeholder
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Stack parameter settings
The configuration SHALL hold, for the stack-parameter tools: the PSTK file path, its SCC column, an optional FIPS column with the values that mark national rows, the column and source unit of each of the four stack quantities, the target unit of each quantity, the plausible range (minimum and maximum, in target units) for each quantity, and the AirToxScreen global fallback values (3.0 m, 0.2 m, 4.0 m/s, 295.4 K). The loader SHALL return these as an immutable typed object.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the stack settings
- **THEN** it returns the PSTK path, column mapping, source and target units, plausible ranges and fallback values

#### Scenario: Invalid stack settings
- **WHEN** a fallback value is not a positive finite number, a range has minimum not below maximum, a fallback lies outside its range, or a quantity is missing from any table
- **THEN** the loader raises an error naming the offending entry

#### Scenario: Unconvertible source unit
- **WHEN** a configured source unit cannot be converted to its target unit
- **THEN** an error naming the quantity is raised before any lookup result is returned

### Requirement: SCC index settings
The configuration SHALL hold, for the SCC retrieval tool: the source table path, its column names, the persisted index directory, the collection name, the data categories and statuses to index, the number of results to return and the indexing batch size. It SHALL separately hold the embedding settings: provider name, model name, API-key environment variable name and request timeout. The loaders SHALL return these as immutable typed objects.

#### Scenario: Settings loaded
- **WHEN** the loaders are asked for the SCC index and embedding settings
- **THEN** they return every listed value from the file

#### Scenario: Invalid SCC index settings
- **WHEN** the result count, batch size or timeout is not a positive number, the category or status list is empty, a column name is missing, the provider is not a supported one, or the model name or collection name is blank
- **THEN** the loader raises an error naming the offending entry

### Requirement: Shared Envirofacts settings
The system SHALL read the Envirofacts base URL, delay between requests, request timeout, maximum retries and retry backoff from an `[efservice]` table, validated on load, and SHALL read the FRS-to-EIS query (path template containing `{frs_id}`, program name and the response field names) from a `[frs]` table.

#### Scenario: Loaded
- **WHEN** the loaders are asked for the Envirofacts and FRS settings
- **THEN** they return the values from the file

#### Scenario: Invalid entry
- **WHEN** a key is missing, a number is negative, non-numeric or a boolean, a timeout is zero, or the FRS path lacks `{frs_id}`
- **THEN** the loader raises a `ValueError` naming the key

### Requirement: NEI stack table settings
The system SHALL read from a `[stack.nei]` table: the shard directory, the shard filename template (containing `{prefix}`), the number of leading ID digits that name a shard, the ID column, the columns holding stack height, stack diameter, exit velocity and exit temperature, the unit each is reported in, the maximum number of candidates, the number of significant digits used to merge near-identical candidates, the raw NEI file location and the raw column names, and SHALL NOT embed them in Python code. Plausible ranges and target units SHALL be the ones configured for stack parameters. A relative path SHALL be resolved against the project root.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the stack settings
- **THEN** it returns the NEI shard location, column mapping, reported units, candidate cap and merge precision

#### Scenario: Changing a column or unit
- **WHEN** a column name or reported unit is edited
- **THEN** subsequent lookups use it with no code change

#### Scenario: Invalid NEI entry
- **WHEN** a key is missing, a unit is not a string, the filename template lacks `{prefix}`, the prefix digits or candidate cap is not a positive integer, or the merge precision is not between 1 and 15
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Meteorology settings
The system SHALL read from a `[meteorology]` table: the archive base URL and path, the hourly variable names requested, the wind speed unit requested, the delay between requests, the request timeout, the maximum retries and the retry backoff, the default reporting year, the first available year and the number of days the archive lags behind the present, the minimum wind speed, the wind direction sector width, and the screening default (wind speed, direction, stability class, temperature), validated on load, and SHALL NOT embed them in Python code.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the meteorology settings
- **THEN** it returns the values from the file

#### Scenario: Changing the archive or the default year
- **WHEN** the base URL or the default year is edited
- **THEN** subsequent lookups use it with no code change

#### Scenario: Invalid entry
- **WHEN** a key is missing, a number is negative, non-numeric or a boolean, a timeout is zero, the sector width does not divide 360 evenly, the first available year is later than the default year, or the screening default has a stability class outside A to F or a wind direction outside 0 to 360
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Population settings
The system SHALL read from a `[population]` table: the tract service URL, layer and the field names used; the Census Data API base URL, ACS vintage year, dataset path and variable codes for the total, under-5, under-18 and 65-and-over counts; the name of the environment variable holding the Census API key (never the key itself); the default, minimum and maximum radius in kilometres; the maximum number of county requests; the request delay, timeout, retries and backoff; and the screening default (residents per square kilometre and the four age-band percentages), validated on load, and SHALL NOT embed them in Python code.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the population settings
- **THEN** it returns the values from the file

#### Scenario: Changing the vintage
- **WHEN** the ACS year is edited
- **THEN** subsequent lookups use it with no code change

#### Scenario: Key variable name only
- **WHEN** the settings are read
- **THEN** they expose the environment variable name, not a key value

#### Scenario: Invalid entry
- **WHEN** a key is missing, a number is negative, non-numeric or a boolean, the minimum radius exceeds the default or the default exceeds the maximum, the screening age bands do not sum to 100 within 0.5, or a variable code is empty
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Exposure settings
The system SHALL read from an `[exposure]` table, and SHALL NOT embed in Python code: the list of (stability class, 10 m wind speed) combinations of the screening meteorology; the distance array (segments of start, end and step, in meters, and the minimum distance); the receptor height; the factor from the 1-hour to the annual average; the wind-profile exponent and the potential temperature gradient of each stability class; the exposure time, frequency and duration, and the cancer averaging time; and, for each age band, the inhalation rate and body weight; each with the source it comes from in a comment. The loader SHALL validate every entry on load.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the exposure settings
- **THEN** it returns the weather combinations, the expanded distance array, the factors and the per-band values from the file

#### Scenario: Changing the distance array
- **WHEN** a segment of the distance array is edited
- **THEN** subsequent calculations use it with no code change

#### Scenario: Invalid entry
- **WHEN** a stability class is not A to F, a wind speed or distance is not positive, a segment does not advance, the annual factor is outside 0 to 1, the frequency is above 365 days, the exposure time is above 24 hours, a band is missing or unknown, or an inhalation rate or body weight is not positive
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Industry settings
The system SHALL read from an `[industry]` table the Envirofacts path that lists the primary NAICS row of a submission (containing `{doc_ctrl_num}`) and the one that looks up a NAICS title (containing `{naics_code}`), the response field names (code, primary indicator, sequence, origin, title), the primary-indicator value, the origin labels for reported and assigned codes, the placeholder codes, and the local NAICS title table (`titles_path`, resolved against the project root, with the names of its code and title columns), validated on load, and SHALL NOT embed them in Python code. The base URL and request policy SHALL be the shared Envirofacts ones.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the industry settings
- **THEN** it returns the paths, field names, labels, placeholder codes and the titles table path and columns from the file

#### Scenario: Invalid entry
- **WHEN** a path lacks its placeholder, a field name, label or column name is empty, the titles path is empty, or a placeholder is not a digit string
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Recent TRI years setting
The `[tri]` table SHALL define `recent_years` (a positive integer), `publication_lag_years` (a non-negative integer: TRI for year N is released by June of N + 1), `max_listed` (a positive integer, the most facilities the inventory tool lists to the model) and a `{after_year}` placeholder in the release path; the window ends with the current year minus `publication_lag_years`. The loader SHALL reject a missing, non-integer, boolean or out-of-range value and a path without the placeholder.

#### Scenario: Window years
- **WHEN** `recent_years` is 2, `publication_lag_years` is 1 and the current year is 2026
- **THEN** the settings give 2023 as the year after which reports count and 2024 as the first year

#### Scenario: Invalid window
- **WHEN** `recent_years` is 0, true or 2.5, `publication_lag_years` is -1, or `max_listed` is 0
- **THEN** the loader raises a `ValueError` naming the key

### Requirement: FRS point settings
The system SHALL read from an `[frs_point]` table the bulk FRS coordinates lookup: its service root URL (`base_url`, a separate service from Envirofacts `efservice`), the path template (containing `{frs_ids}`, a comma-separated list of FRS IDs), the answer field names of the FRS ID, latitude and longitude, and `batch_size`, the most FRS IDs asked in one request (a positive integer), validated on load.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the FRS point settings
- **THEN** it returns the base URL, path, field names and batch size from the file

#### Scenario: Invalid entry
- **WHEN** the path lacks `{frs_ids}`, a key is missing, or `batch_size` is not a positive integer
- **THEN** the loader raises a `ValueError` naming the key

### Requirement: Agent chat model settings
The system SHALL read from an `[agent]` table the chat model that drives the agent: the
provider, the model name, the name of the environment variable holding the provider API key
(never the key itself), the request timeout, the step limit of one agent run and the sampling
temperature, validated on load, and SHALL NOT embed them in Python code. The shipped
temperature SHALL be 0, so a screening assessment is as reproducible as the provider allows.
The program, the web program and the agent evaluation SHALL all build the agent's chat model
from this table through one factory, so they always run the same model with the same
temperature. The factory SHALL accept the API key either injected as a secret value (from the
OS credential store) or read from the named environment variable when none is injected.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the agent settings
- **THEN** it returns the values from the file

#### Scenario: Changing the model
- **WHEN** the model name is edited
- **THEN** the program and the evaluations both use it with no code change

#### Scenario: Temperature reaches the model
- **WHEN** the agent's chat model is built from settings with temperature 0
- **THEN** the model samples at temperature 0

#### Scenario: Injected key
- **WHEN** the chat model is built with an injected key and the environment variable unset
- **THEN** the model is built with the injected key and the environment is not read

#### Scenario: Missing key
- **WHEN** no key is injected and the API-key variable is unset or blank and the chat model is built
- **THEN** building raises an error naming the variable

#### Scenario: Invalid entry
- **WHEN** a key is missing, the model name is empty, the provider is not supported, the timeout is not a positive number or is a boolean, the step limit is not a positive integer, or the temperature is missing, a boolean, or outside 0 to 2
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Evaluation settings
The system SHALL read from an `[evaluation]` table: the judge model provider and name, the name
of the environment variable holding the judge provider's API key (never the key itself), the
names of the tools that run for real during replay (they need no network), the directory of
recorded tool outputs and the directory reports are written to, validated on load, and SHALL NOT
embed them in Python code. The agent's own model SHALL NOT be configured here.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the evaluation settings
- **THEN** it returns the values from the file, with relative directories resolved against the project root

#### Scenario: Changing the judge
- **WHEN** the judge model name is edited
- **THEN** subsequent evaluation runs use it with no code change

#### Scenario: Key variable name only
- **WHEN** the settings are read
- **THEN** they expose the environment variable name, not a key value

#### Scenario: Invalid entry
- **WHEN** a key is missing, the judge model name is empty, or the judge provider is not supported
- **THEN** the loader raises a `ValueError` naming the offending key

### Requirement: Read-across settings
The system SHALL read from a `[read_across]` table, validated on load, and SHALL NOT embed
these values in Python code:
- the PubChem PUG REST URL template, containing `{cas}`, and its request policy (timeout, delay, retries, backoff);
- the embedding model name and maximum token length;
- the fingerprint radius and bit count, and the embedding width;
- alpha, the applicability-domain threshold (calibrated against the catalog's leave-one-out
  score distribution, with that calibration recorded beside the value) and the catalog's column
  names;
- the catalog's shard directory, its shard file-name template (containing `{prefix}`) and the
  number of leading CAS digits that name a shard;
- the Envirofacts `tri_chem_info` path, containing `{start}` and `{end}`, and its page size;
- the CAS, name and inactive-date field names, the inactive-date value meaning "still listed", and whether delisted chemicals are kept (default: no).

The base URL and request policy for `tri_chem_info` SHALL be the shared Envirofacts ones.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the read-across settings
- **THEN** it returns the values from the file, with alpha 0.55 and threshold 0.60 by default

#### Scenario: Invalid entry
- **WHEN** alpha or the threshold is outside [0, 1] or boolean, the URL lacks `{cas}`, the `tri_chem_info` path lacks `{start}` or `{end}`, the shard template lacks `{prefix}`, the prefix length or the timeout, page size or a width or radius is not positive, or a column name is empty
- **THEN** the loader raises a `ValueError` naming the offending key

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

### Requirement: Assessment settings
The system SHALL read from an `[assessment]` table the most facilities fully assessed per call, the most refined with their own stacks per call, the number processed at a time, the SCC similarity floor (greater than 0, at most 1), the most PSTK stacks per facility, how long an inventory is reused (seconds, zero or more), the most worst-case-only facilities listed to the model, and the reanalysis grid cell (degrees, greater than 0) within which facilities share the weather; and from `[assessment.screening]` the HQ threshold and the cancer-risk threshold (both greater than 0) and the screening ambient temperatures (a non-empty list of positive kelvin values), validated on load.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the assessment settings
- **THEN** it returns the values from the file

#### Scenario: Invalid entry
- **WHEN** a count is not a positive integer or is a boolean, the floor is not in (0, 1], the reuse time is negative, a threshold or the cell is not positive, or the temperatures are empty or not all positive numbers
- **THEN** the loader raises a `ValueError` naming the key

### Requirement: EIS lookup settings for many facilities
The `[frs_eis]` table SHALL also give the number of same-site searches run at a time (a positive integer) and how long a facility's EIS IDs are reused (seconds, zero or more), validated on load.

#### Scenario: Invalid entry
- **WHEN** the number of searches is not a positive integer or the reuse time is negative
- **THEN** the loader raises a `ValueError` naming the key

### Requirement: FRS EIS settings
The system SHALL read from an `[frs_eis]` table the bulk FRS-to-EIS lookup and the same-site search: the service root URL, the EIS registrations path template (containing `{frs_ids}`), the site rows path template (containing `{frs_ids}`), the same-name path template (containing `{name}` and `{state}`), the answer field names (FRS ID, EIS ID, site name, state, latitude, longitude), `batch_size` (a positive integer) and `max_twin_distance_km` (a positive number), validated on load.

#### Scenario: Settings loaded
- **WHEN** the loader is asked for the FRS EIS settings
- **THEN** it returns the URL, path templates, field names, batch size and distance from the file

#### Scenario: Invalid entry
- **WHEN** a path lacks its placeholder or does not start with `/`, a field name is empty, `batch_size` is not a positive integer or the distance is not a positive number
- **THEN** the loader raises a `ValueError` naming the key

### Requirement: CompTox certificate waiver setting
The `[comptox]` table SHALL carry `accept_expired_certificate`, a boolean, validated on load, with a comment saying it is for a lapse of the service's certificate and is to be turned off again.

#### Scenario: Not a boolean
- **WHEN** the value is missing or not a boolean
- **THEN** the loader raises a `ValueError` naming the key

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
