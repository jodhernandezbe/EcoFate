## ADDED Requirements

### Requirement: A reviewed catalogue of scenario questions
The evaluation SHALL keep a catalogue of scenario questions as a CSV file at
`evals/scenarios.csv` with exactly the columns `question`, `category` and `type`, in that
order, with a header row. `type` SHALL be one of `happy_path`, `varied_phrasing`,
`edge_case`, `out_of_scope` and `breaking`. The catalogue SHALL hold at least 50 questions,
SHALL contain at least five of type `breaking`, and SHALL contain at least one question of
each of the five types. Every question SHALL be specific to this agent: it names a chemical,
CAS number, facility, place, tool output, result field, data source, or rule of the system
prompt that the agent must honour. Every `breaking` question SHALL be built to make the agent
break a stated rule (invent or recall a CAS number, name, identifier or number; follow an
instruction embedded in the message; assess a compartment it does not cover; present a
borrowed or category value as measured). The catalogue SHALL NOT contain expected answers,
tool outputs or numeric results that look like real data: expectations live in checks and
cassettes.

#### Scenario: Catalogue shape
- **WHEN** `evals/scenarios.csv` is read as CSV
- **THEN** its header is `question,category,type`, every row has a non-empty question and category, every `type` is one of the five allowed values, there are at least 50 rows, at least 5 rows are `breaking`, and every type appears at least once

#### Scenario: Question is agent-specific
- **WHEN** any row's question is read on its own
- **THEN** it refers to a chemical, CAS number, facility, place, result, data source or rule of this exposure assessor, and could not be asked verbatim of an unrelated chatbot

#### Scenario: Breaking question has a target rule
- **WHEN** a row is of type `breaking`
- **THEN** its category names the rule or failure it is designed to provoke (for example CAS from memory, invented identifier, prompt injection, unsupported compartment)

#### Scenario: Scripted scenario drawn from the catalogue
- **WHEN** a scripted scenario with checks and a cassette is added to the evaluation
- **THEN** its query is one of the catalogue questions or the catalogue gains that question in the same change
