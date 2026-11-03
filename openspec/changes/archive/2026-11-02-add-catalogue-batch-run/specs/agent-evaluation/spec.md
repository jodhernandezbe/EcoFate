## MODIFIED Requirements

### Requirement: A reviewed catalogue of scenario questions
The evaluation SHALL keep a catalogue of scenario questions as a CSV file at
`evals/catalogue/scenarios.csv` with exactly the columns `question`, `category` and `type`,
in that order, with a header row. `type` SHALL be one of `happy_path`, `varied_phrasing`,
`edge_case`, `out_of_scope` and `breaking`. The catalogue SHALL hold at least 50 questions,
SHALL contain at least five of type `breaking`, and SHALL contain at least one question of
each of the five types. Every question SHALL be specific to this agent: it names a chemical,
CAS number, facility, place, tool output, result field, data source, or rule of the system
prompt that the agent must honour. Every `breaking` question SHALL be built to make the agent
break a stated rule (invent or recall a CAS number, name, identifier or number; follow an
instruction embedded in the message; assess a compartment it does not cover; present a
borrowed or category value as measured). The catalogue SHALL NOT contain expected answers,
tool outputs or numeric results that look like real data: expectations live in checks and
cassettes. The evaluation SHALL read the catalogue through one reader that rejects a file
with a wrong header, an unknown type, an empty cell or a row with the wrong number of cells,
naming the line; the batch run and the shape test SHALL use that reader.

#### Scenario: Catalogue shape
- **WHEN** `evals/catalogue/scenarios.csv` is read as CSV
- **THEN** its header is `question,category,type`, every row has a non-empty question and category, every `type` is one of the five allowed values, there are at least 50 rows, at least 5 rows are `breaking`, and every type appears at least once

#### Scenario: Malformed catalogue is rejected
- **WHEN** the reader is given CSV text with a missing column, an unknown type, an empty question or an extra cell
- **THEN** it raises an error that names the problem and the line, and no row is returned

#### Scenario: Question is agent-specific
- **WHEN** any row's question is read on its own
- **THEN** it refers to a chemical, CAS number, facility, place, result, data source or rule of this exposure assessor, and could not be asked verbatim of an unrelated chatbot

#### Scenario: Breaking question has a target rule
- **WHEN** a row is of type `breaking`
- **THEN** its category names the rule or failure it is designed to provoke (for example CAS from memory, invented identifier, prompt injection, unsupported compartment)

#### Scenario: Scripted scenario drawn from the catalogue
- **WHEN** a scripted scenario with checks and a cassette is added to the evaluation
- **THEN** its query is one of the catalogue questions or the catalogue gains that question in the same change

## ADDED Requirements

### Requirement: Batch run over the catalogue
The evaluation SHALL provide a command, `python -m evals catalogue`, that sends every
catalogue question to the agent, in file order, one turn each, by the same path the program
uses (the configured chat model and step limit, the stored keys with their environment
fallback, telemetry when configured, every model call metered). For each row it SHALL record:
the question, category and type as in the CSV; the agent's final answer; the execution time
in seconds; the token counts of the run (input, cached input, output, total, the number of
model calls and whether every call reported usage); the estimated cost in USD with its status
and price date, or no figure when the model has no configured price; and the error that ended
the run, or none. The results SHALL be written as one JSON array to a time-stamped folder
under the configured report directory, under the configured result file name. The command
SHALL print, per row, its position and question before the run and its time and cost after,
and at the end the number of rows, the output path, and the total cost (or that it could not
be priced). A row whose run ends in an expected error (step limit exceeded, a service or
provider request failure) SHALL be recorded with that error and an empty answer, and the
command SHALL go on to the next row. A setup error (no API key for the agent's model) SHALL
stop the command before any row runs. The catalogue path and result file name SHALL come from
the evaluation settings.

#### Scenario: Every row answered
- **WHEN** the command runs with the keys available and every run finishes
- **THEN** the results file holds one object per CSV row, in order, each with a non-empty answer, a positive execution time, token counts, a cost object and `error: null`, and the command prints the output path and total cost

#### Scenario: One row exceeds the step limit
- **WHEN** one question drives the agent past the configured step limit
- **THEN** that row is recorded with the error text and an empty answer, the other rows are unaffected, and the command exits normally

#### Scenario: Model without a configured price
- **WHEN** the configured model has no entry in the pricing table
- **THEN** each row's cost has no USD figure and the status `unpriced`, the token counts are still recorded, and the final summary says the run could not be priced

#### Scenario: Agent key missing
- **WHEN** neither the keychain nor the environment provides the agent's API key
- **THEN** the command fails before sending any question and names the variable

#### Scenario: Results do not enter version control
- **WHEN** the command writes its results
- **THEN** they land under the evaluation report directory, which is ignored by git
