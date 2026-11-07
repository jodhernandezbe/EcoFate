# agent-evaluation Specification

## Purpose

Behavioral evaluation of the exposure-assessor agent: runs the real agent with an OpenAI chat
model on scripted scenarios and checks which tools it calls, with what arguments, and what its
final report says, so regressions in prompts or tool descriptions are caught.

## Requirements

### Requirement: Scenario runs are captured as records
The evaluation SHALL run the production agent graph (the registered tools with their real
names, descriptions and argument schemas, and the production system prompt) once per scenario
and SHALL capture each run as one record holding: the scenario id, the user query, every tool
call in order with its name and arguments, every tool output, the final report text, and
whether the run completed or the error that ended it. A run that ends in an error SHALL still
produce a record.

#### Scenario: Completed run
- **WHEN** a scenario is run and the agent finishes with a final answer
- **THEN** its record lists the tool calls in the order made, their outputs and the final report, and is marked completed

#### Scenario: Run ends in an error
- **WHEN** the agent run raises (for example it exceeds the step limit)
- **THEN** the record is marked not completed with the error message and the scenario fails

### Requirement: The agent under test uses the program's chat model
The agent under test SHALL be driven by the same chat model the program runs: the one
configured in the agent settings (provider, model, API-key variable, timeout and step limit),
built by the program's own chat model factory. The evaluation SHALL NOT name or construct an
agent model of its own. The judge model SHALL come from the evaluation settings. When an API key
is not set, evaluation runs SHALL be skipped with a message naming the variable, not fail.

#### Scenario: Model swapped in settings
- **WHEN** the agent model name is edited in the settings
- **THEN** the program and the next evaluation run both use that model

#### Scenario: Missing key
- **WHEN** the OpenAI key variable is unset or empty
- **THEN** the evaluation tests are skipped and say which variable is missing

### Requirement: Tool outputs are recorded from live services and replayed
Tools that call network services SHALL be replayed from recordings made by running those tools
against the live services; recordings SHALL NOT be written by hand. Tools that need no network
(the exposure calculation) SHALL run for real during replay. A replayed tool SHALL return the
recorded output for a call whose arguments match a recording. A call with no matching recording
SHALL fail closed: the tool returns an error result to the agent saying no recording exists, and
the record marks the call as unrecorded so the scenario fails with a message to re-record. A
recording mode SHALL run the scenario with the live tools and save every network tool output.

#### Scenario: Recorded call
- **WHEN** the agent calls a network tool with arguments that match a recording
- **THEN** it receives the recorded output and no network request is made

#### Scenario: Unrecorded call
- **WHEN** the agent calls a network tool with arguments that have no recording
- **THEN** the tool returns an error result, the call is marked unrecorded and the scenario fails naming the call

#### Scenario: Offline tool
- **WHEN** the agent calls the exposure calculation during replay
- **THEN** the real calculation runs on the arguments the agent passed

#### Scenario: Recording
- **WHEN** a scenario is run in recording mode
- **THEN** each network tool output is saved so a later replay reproduces it

### Requirement: Deterministic checks score tool use and completion
Each scenario SHALL declare deterministic checks evaluated on its record by the evaluation
framework, each yielding pass or fail with a reason: which tools must, must not, or may be
called; how many times a tool is called relative to the tool outputs (for example once per
assessed facility); which arguments a call must carry (for example the CAS number asked for, or
every stack candidate a facility's stack result returned); call order where it matters; that no
call was unrecorded; and that the run completed. Checks SHALL compare against values found in
the record's tool outputs, never against numbers written into the check.

#### Scenario: Forbidden tool called
- **WHEN** a scenario forbids a tool and the record contains a call to it
- **THEN** that check fails and names the call

#### Scenario: Count tied to tool output
- **WHEN** a check requires one exposure calculation per assessed facility
- **THEN** the expected facilities are taken from the stack requests in the record, and a different number of exposure calls for a facility fails

#### Scenario: Arguments tied to tool output
- **WHEN** a check requires the exposure calculation to carry every NEI candidate of a facility
- **THEN** the expected candidates are taken from the stack result in the record, and a call missing any of them fails

### Requirement: LLM judges score report qualities
Report qualities that code cannot verify SHALL be scored by an OpenAI judge model named in the
evaluation settings. Each judge SHALL answer one narrow pass/fail criterion about the final
report, given the report and, where needed, the tool outputs, and SHALL record its reasoning.
A judge that cannot be reached SHALL make its check fail, not pass.

#### Scenario: Criterion met
- **WHEN** the final report satisfies a judge criterion
- **THEN** the judge check passes and its reasoning is kept in the results

#### Scenario: Judge unavailable
- **WHEN** the judge call fails
- **THEN** the check fails with the error as its reason

### Requirement: Each evaluation run writes a report
Each evaluation run SHALL write a human-readable report per scenario, showing every check and
judge with its result and reason and an overall pass/fail, into a folder for that run under a
configured directory that is not committed.

#### Scenario: Report written
- **WHEN** an evaluation run finishes
- **THEN** the run's folder holds one report per scenario run, with one entry per check and judge

### Requirement: Evaluations are opt-in
Evaluation tests SHALL be marked so they are excluded from the default test run and from the
pre-commit hooks, and SHALL run when the marker is selected explicitly.

#### Scenario: Default test run
- **WHEN** the default test command runs
- **THEN** no evaluation test runs and no model is called

#### Scenario: Explicit selection
- **WHEN** the evaluation marker is selected
- **THEN** the evaluation tests run

### Requirement: Scenario catalogue
The evaluation SHALL keep a catalogue of scenarios, each with an id, the user query, its
recordings and its checks. A scenario that depends on behavior not yet implemented SHALL be
listed as blocked with the reason and SHALL NOT be run. The catalogue SHALL cover: happy paths,
tool use and fallback order, edge cases, and failure modes.

#### Scenario: Blocked scenario
- **WHEN** the catalogue lists a scenario as blocked
- **THEN** it is reported as skipped with its reason

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

### Requirement: Chemical given by name only
The catalogue SHALL include a scenario in which the user names a chemical by its common name
(formaldehyde) and gives no CAS number. It SHALL pass only when: the run completed; no tool was
called; the final report states no CAS number; and an LLM judge confirms the reply asks the user
for the CAS registry number and presents no facility, concentration or risk result.

#### Scenario: CAS filled in from memory
- **WHEN** the agent calls a tool with a CAS number it supplied itself
- **THEN** the no-tool-call check fails and names the call

#### Scenario: Reply does not ask for the CAS number
- **WHEN** the final reply does not ask for the CAS number
- **THEN** the LLM judge check fails with the judge's reasoning

### Requirement: Full assessment of a facility with its own stacks
The catalogue SHALL include a scenario asking for an assessment of a chemical given by CAS number
whose recorded inventory returns facilities that have NEI stack candidates. It SHALL pass only
when: the run completed with no unrecorded call; the chemical's properties and the emissions
inventory were requested with the CAS number asked for; every facility the agent assessed had
its NEI stacks requested with its `frs_id`, its weather and its population requested with that
facility's coordinates; the exposure calculation ran exactly once per assessed facility, carrying
every NEI stack candidate of that facility and its emission rate; the industry, SCC process and
SCC stack tools were not called for a facility that had NEI candidates; and a judge confirms the
report gives a summary, a per-facility table with units showing the range over stacks and both
the worst and the representative case, the source of each input, and a limitations section.

#### Scenario: One stack evaluated out of several
- **WHEN** a facility has several NEI candidates and the exposure call for it carries only one
- **THEN** the candidate-coverage check fails naming the missing candidates

#### Scenario: Some candidates left out
- **WHEN** a facility has ten NEI candidates and the exposure call for it carries six
- **THEN** the candidate-coverage check fails naming the missing candidates

#### Scenario: One call per stack
- **WHEN** the agent runs the exposure calculation once per candidate instead of once per facility
- **THEN** the one-call-per-facility check fails

#### Scenario: Unneeded fallback
- **WHEN** a facility has NEI candidates and the agent also calls the SCC stack tool for it
- **THEN** the forbidden-tool check fails

#### Scenario: Complete assessment
- **WHEN** the agent follows the chain for every facility it assesses and writes the full report
- **THEN** every check passes

### Requirement: Cassette current with the tools
A scenario's cassette SHALL be recorded while every service it needs answers (a recording made during an outage carries the outage, not the data), and SHALL hold a recording for every call the agent can make on either route it may take (the batch assessment, or the chain by hand with the current tool signatures). A replay that hits an unrecorded call SHALL fail the scenario and be answered by re-recording it, never by editing the cassette.

#### Scenario: Tool signature changed
- **WHEN** a tool the agent calls gains an argument and the agent now passes it
- **THEN** the replay reports the call as unrecorded and the scenario is re-recorded

#### Scenario: Service outage during recording
- **WHEN** a service fails while a scenario is being recorded
- **THEN** the recording is not kept as the cassette

### Requirement: The report names each input's source
A scenario MAY declare a deterministic check that the final report names the source of each input the run obtained: for every weather, residents and properties result in the record, the distinctive part of its `source` text (for example "era5", "ACS", "CompTox", a benchmark source name) SHALL appear in the report, and the chemical SHALL be referred to by the name the properties result gave or by its CAS number, never by another name. The expected strings SHALL come from the record's tool outputs.

#### Scenario: Weather source paraphrased
- **WHEN** the weather result's source is "Open-Meteo era5 reanalysis 2024" and the report says only "local weather"
- **THEN** the check fails and names the missing source

#### Scenario: Invented chemical name
- **WHEN** the properties result has no name and the report calls the chemical by a name
- **THEN** the check fails

### Requirement: Recordings cover every route to the same outcome
A scenario SHALL be able to list extra tool calls (a tool and its arguments). Recording mode
SHALL make them after the agent run, through the same recording wrapper, so the cassette holds
the outputs of routes the agent did not take in that run. A separate recording command SHALL
make only a scenario's extra calls, without running the agent, and SHALL add their outputs to
the existing cassette, keeping every recording already there; a recording for the same tool and
arguments is replaced by the new one. Extra calls SHALL be made with the tool's full argument
schema so their key equals the key of an agent call that omits the optional arguments.

#### Scenario: Batch route recorded beside the by-hand route
- **WHEN** a scenario lists the batch assessment as an extra call and its cassette is recorded
- **THEN** the cassette holds the batch output as well as the per-facility outputs, and a replayed agent that takes either route finds its recordings

#### Scenario: Extending a cassette
- **WHEN** only the extra calls are recorded for a scenario that already has a cassette
- **THEN** the earlier recordings stay and the extra outputs are added

#### Scenario: Call omitting optional arguments
- **WHEN** the agent calls a recorded tool with only its required arguments
- **THEN** the call finds the recording made from an extra call that gave the same required arguments

### Requirement: LLM judge over the catalogue results
The evaluation SHALL provide a judge that labels one catalogue answer as `good` or `bad`
from the question and the answer alone, returning a structured verdict with a `reasoning`
field (the step-by-step check of the criteria, written before the label), a `label` field
(`good` or `bad`) and a `failure` field (one of `hallucination`, `rule-break`,
`wrong-scope`, `incomplete`, `incorrect`, `other`, or none when the label is `good`). The
judge SHALL NOT be shown the human label, the row's category, its type, or any other judge's
verdict. The judge model SHALL be the one named in the evaluation settings (provider, model,
API-key variable, timeout), built through the program's chat-model factory. The judge prompt
SHALL be a prompt file loaded through the prompt registry and SHALL state, as criteria, the
rules the agent must follow and the failure patterns found during labelling: a CAS number
recalled, suggested or confirmed from memory (including as an example, or after an
instruction embedded in the message); an off-topic task performed because it mentions the
domain (writing code, drafting a legal letter, arguing policy); a value asked for that the
requested result does not use; facilities dropped, counts that contradict each other, or a
state-wide request silently narrowed; the off-topic half of a mixed request ignored instead
of declined; a reply that ends by announcing a next step or asking whether to proceed; and
claims about people or places no tool reports.

#### Scenario: Structured verdict
- **WHEN** the judge is given a question and an answer
- **THEN** it returns a verdict whose `label` is `good` or `bad`, whose `reasoning` is non-empty, and whose `failure` is one of the listed categories when the label is `bad` and absent when it is `good`

#### Scenario: Judge sees no labels
- **WHEN** the judge prompt for a row is built
- **THEN** it contains the question and the answer and does not contain the row's human label, category, type, or the human reasons

#### Scenario: Judge call fails
- **WHEN** the judge model raises or returns no parseable verdict for a row
- **THEN** that row is recorded with the error and no label, and the other rows are still judged

### Requirement: Judge scored against the human labels
The evaluation SHALL provide a command, `python -m evals judge <run-dir>`, that judges every
row of the run's results file, writes the verdicts to a `judged.json` file in the same
folder (per row: index, question, human label, human failure, judge label, judge failure,
reasoning, error), and prints: the number of rows judged and failed; accuracy, precision and
recall against the human labels with `bad` as the positive class, computed over the rows
that received a judge label; the confusion matrix (true good/bad against predicted
good/bad); and every disagreement, with the row index, question, human label with its
failure category, judge label with its failure category, and the judge's reasoning. When no
row received a label the metrics SHALL be reported as undefined, not zero. The human labels
SHALL be read from the run's `labels.json`; a run without one, or whose labels do not match
the results row for row, SHALL stop the command before any judge call.

#### Scenario: Metrics over labelled rows
- **WHEN** the command runs on a folder holding `catalogue.json` and a matching `labels.json`
- **THEN** it writes `judged.json`, prints accuracy, precision and recall over the judged rows with `bad` positive, the confusion matrix, and one block per disagreement

#### Scenario: Precision and recall with no positive predictions
- **WHEN** the judge labels every row `good`
- **THEN** recall is 0 when any human label is `bad`, precision is reported as undefined, and accuracy is the share of human `good` rows

#### Scenario: Labels missing or mismatched
- **WHEN** the folder has no `labels.json`, or its rows do not match the results by index and question
- **THEN** the command fails with a message naming the problem and makes no judge call

#### Scenario: Judge prompt improved
- **WHEN** the judge prompt file is edited and the command re-run on the same folder
- **THEN** `judged.json` is overwritten with the new verdicts and the metrics reflect them, with no other input changed
