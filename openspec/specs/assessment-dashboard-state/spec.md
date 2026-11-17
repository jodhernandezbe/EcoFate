# assessment-dashboard-state Specification

## Purpose

Turns the agent's tool calls and results into the typed state shown on the left pane, so the
dashboard reflects exactly what the tools reported and never shows a number no tool produced.

## Requirements

### Requirement: State derived only from tool calls and results
The dashboard state of a thread SHALL be rebuilt after every finished tool call from that
thread's tool-call arguments and tool results alone. It SHALL NOT parse assistant prose, SHALL
NOT compute, estimate or convert scientific values itself (beyond selecting maxima the tools
already returned), and SHALL carry, for each value, the tool `source` and warnings that came
with it. A field no tool reported SHALL be absent (null) with a reason; the UI renders it as
"not reported".

#### Scenario: Values come from tools
- **WHEN** the meteorology tool returns a wind speed of `w` m/s
- **THEN** the dashboard meteorology shows `w` with that result's `source` and warnings

#### Scenario: Not yet evaluated
- **WHEN** no read-across tool call has been made in the thread
- **THEN** the chemical provenance is marked "not evaluated" rather than "direct TRI match"

### Requirement: Untrusted results fail closed
A tool result that is not valid JSON, has the wrong shape, contains non-finite numbers or a
boolean where a number is expected, or has coordinates outside -90..90 / -180..180, SHALL be
left out of the dashboard with a warning; it SHALL NOT break the stream or the rest of the
state. A tool that returned an error SHALL contribute nothing.

#### Scenario: Malformed result
- **WHEN** a tool result is not JSON
- **THEN** that result is skipped, a dashboard warning is added and the turn continues

#### Scenario: Bad coordinates
- **WHEN** an inventory record has latitude 123
- **THEN** that facility is not placed on the map and a warning names its FRS ID

### Requirement: Facilities
The state SHALL list one facility per FRS ID from the emissions inventory results (latest
result wins; the complete list the tool returns beside the text the model reads, falling back to the
facilities in that text), with name, address fields, coordinates, TRI document control number, reported
release and its unit, emission rate (g/s), assumed operating hours (h/yr), medium, reporting
year, the NAICS subsector code and title the inventory reported for it, the TSCA conditions of use and life cycle stages the inventory reported for it (with the
note when there are none), and the queried CAS number. It SHALL attach, by matching identifiers only:
- industry (NAICS code, title, origin) from the industry tool, matched by document control number;
- stack candidates and their source from the NEI stack tool, matched by FRS ID;
- receptors (population, age distribution, radius used, source) from the population tool,
  matched by coordinates equal to the facility's within a configured tolerance;
- exposure results (per-stack results and ranges) from the exposure tool, matched by an
  emission rate equal to exactly one facility's emission rate.
A result that matches no facility, or more than one, SHALL NOT be attached to any facility and
SHALL be reported as an unattributed result.

#### Scenario: Stacks attached
- **WHEN** the NEI stack tool is called with a facility's FRS ID
- **THEN** that facility shows its candidates with source NEI

#### Scenario: Ambiguous exposure result
- **WHEN** two facilities share the emission rate passed to the exposure tool
- **THEN** the exposure result is attached to neither and is listed as unattributed

#### Scenario: Conditions of use carried
- **WHEN** the inventory record has two conditions of use and two life cycle stages
- **THEN** the facility shows both, unchanged, and no condition is derived by the workspace

#### Scenario: Older state without conditions
- **WHEN** a record has no conditions fields
- **THEN** the facility has empty lists and no note, and the state still builds

#### Scenario: Subsector carried
- **WHEN** the inventory record has subsector "325" with a title
- **THEN** the facility shows both unchanged, and a record without them gives nulls

### Requirement: Stack provenance tier
Each stack shown SHALL carry a provenance tier derived only from its reported source: Tier 1
"Empirical NEI" for NEI, Tier 2 "PSTK by SCC" for PSTK (with the SCC, and its description and
match score when an SCC lookup in the same thread returned that SCC), and Tier 3 "EPA global
default" for the global default. A stack with no source SHALL have no tier.

#### Scenario: Generic stack
- **WHEN** a stack's source is the AirToxScreen global default
- **THEN** its tier is "Tier 3: EPA global default"

#### Scenario: PSTK with lookup
- **WHEN** a PSTK stack's SCC was returned by an SCC lookup in the same thread
- **THEN** the tier shows that SCC's description and score

### Requirement: Executive summary
The state SHALL expose a summary of:
- the highest worst-case and representative hazard quotient and lifetime cancer risk across
  attributed facility ranges, each with the facility and stack that gave it, and a status of
  `below`, `near` or `above` the threshold of concern (HQ thresholds and cancer-risk thresholds
  from configuration);
- the chemical: CAS number as queried, molecular weight, inhalation RfC and IUR from the
  chemical properties tool with their sources, and the read-across outcome (direct TRI match,
  read-across surrogate with surrogate CAS, name, cosine, Tanimoto, hybrid score and
  applicability-domain flag, or unresolved);
- receptors: the population, radius and age distribution of the selected facility (the highest
  risk one, or the only one);
- meteorology: wind speed, direction (from), ambient temperature, stability class and source, with the
  point it is for and the facility at that point (none when the point is not one of the facilities).

#### Scenario: Status above concern
- **WHEN** the highest worst-case HQ exceeds the configured threshold of concern
- **THEN** the HQ status is `above`

#### Scenario: Surrogate out of domain
- **WHEN** the read-across result has `within_applicability_domain` false
- **THEN** the provenance shows the surrogate scores flagged as outside the applicability domain

#### Scenario: No exposure yet
- **WHEN** no exposure tool has returned
- **THEN** HQ and cancer risk are absent with reason "not yet computed"

### Requirement: Map framing hints
The state SHALL include the bounding box of all placed facilities and a monotonically increasing
version that changes only when the set of placed facilities or receptor buffers changes, so the
map moves the camera only on real changes.

#### Scenario: New facilities found
- **WHEN** an inventory result adds facilities
- **THEN** the bounding box covers them and the framing version increases

#### Scenario: Unrelated update
- **WHEN** only a chemical properties result arrives
- **THEN** the framing version does not change

### Requirement: Batch results attach by FRS ID
Each facility of a batch assessment SHALL be placed on the map from its record and given its stacks (with their tier and SCC), weather, residents and exposure, attached by FRS ID, so facilities with the same emission rate keep their own results. A later single-tool result for a facility SHALL replace the batch one. An invalid facility item SHALL be left out with a warning; a batch result without its details SHALL be skipped with a warning.

#### Scenario: Same emission rate
- **WHEN** two assessed facilities have the same emission rate
- **THEN** each shows its own stacks and risk

#### Scenario: Later single result
- **WHEN** an exposure result for one facility follows the batch result
- **THEN** that facility shows the later result

### Requirement: Screening shown per facility
Each facility of a batch assessment SHALL carry its screening outcome: fully assessed, worst case only, screened out at the bound or with its own stacks, or not assessed, with the bound HQ and cancer risk and the reason. A screened-out facility SHALL be placed on the map from its record even when the inventory was not listed. The facility card SHALL say why a facility has no stacks or risk (screened out, with its bound and the threshold; or not assessed, with the reason the assessment gave; or not covered by a batch assessment yet) instead of implying the values are missing, and SHALL say when only the worst case was computed. A not-assessed result SHALL NOT replace a facility's real result, and one for an FRS ID with no placed facility SHALL be ignored.

#### Scenario: Screened-out facility
- **WHEN** a facility was screened out at the bound
- **THEN** its card shows the bound HQ, the threshold and that it was screened out, not "not reported"

#### Scenario: Worst case only
- **WHEN** a facility kept only its own-stack worst case
- **THEN** its card shows its stacks and worst-case risk and says the representative case, weather and residents were not computed

#### Scenario: Not assessed with a reason
- **WHEN** the batch assessment returns a facility as not assessed with a reason
- **THEN** its card says "Not assessed" and the reason, not that stack parameters were not obtained

#### Scenario: Not covered yet
- **WHEN** a facility is on the map from the inventory but no batch assessment has covered it
- **THEN** its card says that no batch assessment has covered it yet

### Requirement: The chemical carries its name
The workspace's chemical SHALL carry the preferred name the properties result gave (None when it gave none), with its source among the chemical's sources, taken only from that result.

#### Scenario: Name reported
- **WHEN** a properties result with a preferred name is projected
- **THEN** the chemical shows that name and its source

#### Scenario: Name absent
- **WHEN** the properties result has no name
- **THEN** the chemical's name is None and nothing else fills it

### Requirement: Occupational exposure and operational profile on each facility
The state SHALL carry, for each facility, the `occupational_exposure` and `operational_profile` exactly as the assessment tool returned them (the TWA, benchmark and its source, limit ratio, hazard quotient, cancer risk, tier, warnings; the NAICS code, life cycle stages, condition-of-use categories, CDR sector, operating days, hours per day and annual operating hours), each absent (null) with its reason when the tool did not report it, under the same fail-closed rules as the other values. They SHALL be sent in the `workspace_update` event and described in the generated schema and TypeScript types.

#### Scenario: Values come from the tool
- **WHEN** the assessment reports a TWA for a facility
- **THEN** the facility's state shows that value and its source

#### Scenario: Non-finite value
- **WHEN** a result contains a non-finite or boolean number
- **THEN** that value is left out with a warning and the rest of the facility is kept

#### Scenario: Not reported
- **WHEN** the tool reported no occupational result for a facility
- **THEN** the fields are null with a reason and the facility's community values are unaffected

#### Scenario: Contract
- **WHEN** the schema is generated
- **THEN** the TypeScript types include the two new objects and the contract test passes

### Requirement: Highest worker values across facilities
The state SHALL carry a worker risk summary with the highest limit ratio, worker hazard quotient and worker cancer risk over the assessed facilities, for the baseline and the worst case, each naming the facility it comes from, that facility's band and the evidence its value rests on (monitoring or activity model, with the driving activity); each is a selection among the values the tools returned, never a sum, mean or conversion. When no facility has a worker result the summary SHALL be empty with a reason.

#### Scenario: Highest value
- **WHEN** two facilities have worker results
- **THEN** each figure of the summary is the larger of the two and names its facility, its band and its evidence

#### Scenario: Nothing yet
- **WHEN** no facility has a worker result
- **THEN** every figure is absent and a reason is given

### Requirement: Each facility carries its exposure graph
The state SHALL carry, for each facility, an exposure graph: lanes (one per pathway, with whether it is
available and why not, and its band), nodes (source facility, each evaluated stack or the driving worker
activity, the pathway, the route, each receptor group and the endpoint) and edges (each with the quantity
it carries). Every quantity SHALL carry its value as the tools reported it, its unit and its source, or no
value and a reason; no value SHALL be computed, converted or estimated to build the graph. Fixed text and
units SHALL come from configuration. The graph SHALL be sent in `workspace_update` and described in the
generated schema and types.

#### Scenario: Community branches
- **WHEN** a facility has two evaluated stacks and residents in four age bands
- **THEN** its graph has two stack nodes feeding the outdoor air and four age-band receptor nodes, each with its dose

#### Scenario: Worker lane
- **WHEN** a facility has an occupational result
- **THEN** the worker lane carries the evidence, the driving activity and its generation rate, the worst-case and baseline concentrations, whether the saturation cap applied, the TWA, the limit and its source, the ratio and the band, with the fugitive release as context

#### Scenario: Unavailable lane
- **WHEN** a facility has no occupational result
- **THEN** the worker lane is marked unavailable with the configured reason and has no nodes

#### Scenario: Absent quantity
- **WHEN** a tool did not report a value (for example no cancer risk)
- **THEN** that quantity has no value and carries the reason, and the rest of the graph is unchanged

#### Scenario: Contract
- **WHEN** the schema is exported
- **THEN** the TypeScript types include the graph and the contract check passes

### Requirement: Scenarios and their drivers in the workspace
The workspace SHALL carry, for each pathway and quantity that has a scenario, the driving facility and its worst-case scenario in the generic shape, and for every assessed facility its scenarios with their receptors, projected from tool results only. A scenario or receptor list that is not valid SHALL be left out alone with a warning. A scenario SHALL never mix values of different facilities or stacks.

#### Scenario: Driver per result
- **WHEN** a run assesses several facilities
- **THEN** the workspace names the driving facility of each result, which may differ from result to result

#### Scenario: Invalid scenario
- **WHEN** one facility's scenario is not valid
- **THEN** it is left out with a warning and the others are kept

#### Scenario: Older server
- **WHEN** the server sends no scenarios
- **THEN** the workspace has none and the dashboard shows the results it showed before

### Requirement: Band boundaries in the client settings
The client settings SHALL carry the boundaries of the screening bands (lower and upper, for the hazard quotient, the cancer risk and the limit ratio) from the one configuration block that defines them, for both pathways, in place of the worker-only tier boundaries.

#### Scenario: Settings read
- **WHEN** the client settings are requested
- **THEN** they hold the band boundaries and no worker-only tier boundaries

#### Scenario: Contract
- **WHEN** the schema is exported
- **THEN** the TypeScript types include the band boundaries and the contract check passes

### Requirement: Screened-out facilities show their worker result
The workspace SHALL attach a screened-out facility's occupational result and operating profile to that facility, beside its screening outcome, and SHALL leave its community exposure absent. A screened-out entry without a worker result (an earlier saved form) SHALL give the facility no worker result, and an invalid worker result SHALL leave out only itself, with a warning.

#### Scenario: Worker result of a screened-out facility
- **WHEN** the batch assessment screened a facility out and gave it a worker result
- **THEN** the facility has its screening outcome, no community exposure, and the worker result and profile

#### Scenario: Earlier saved form
- **WHEN** a saved screened-out entry has no worker result
- **THEN** the facility has no worker result and nothing else changes

### Requirement: Total annual air release of each facility
Each facility SHALL carry its total annual air release in kg/yr: the stack release, converted from the
unit TRI reported to kg/yr by the shared unit converter, plus the TRI fugitive air release, which is
already in kg/yr. A part that is absent SHALL count as absent, never as zero. The total SHALL be the
sum of the parts that are present. It SHALL be absent, with a configured reason, when no part is present
or when the stack unit cannot be converted. When the stack unit cannot be converted, the fugitive part
alone SHALL NOT be passed off as the total. The target unit, the unit aliases and the reasons SHALL come
from configuration.

#### Scenario: Stack and fugitive
- **WHEN** a facility reports a stack release in pounds and a fugitive release in kg/yr
- **THEN** its total is the stack release converted to kg/yr plus the fugitive release

#### Scenario: Worker-only facility
- **WHEN** a facility has a fugitive release and no stack release
- **THEN** its total is its fugitive release

#### Scenario: Unknown unit
- **WHEN** the stack release's unit cannot be converted
- **THEN** the total is absent with the configured reason, even if a fugitive release exists

#### Scenario: Nothing reported
- **WHEN** a facility has neither release
- **THEN** the total is absent with the configured reason

#### Scenario: Contract
- **WHEN** the schema is exported
- **THEN** the TypeScript types include the total and its reason, and the contract check passes

### Requirement: The workspace carries the run's worst-case chain
The workspace state SHALL carry `worst_case_chain`, the run-wide worst-case graph, in the same graph shape as a facility's exposure graph (lanes, nodes, edges). It SHALL be rebuilt from the facilities and the scenario drivers every time either changes, and it SHALL be sent in `workspace_update` and described in the generated schema and types. When no facility has been assessed, it SHALL be an empty graph, never absent. The per-facility exposure graphs SHALL be unchanged.

#### Scenario: Rebuilt on update
- **WHEN** a later tool result changes which facility drives the hazard quotient
- **THEN** the next `workspace_update` carries a chain whose outdoor-air lane holds the new driver's values

#### Scenario: Before any assessment
- **WHEN** the workspace has facilities but no scenario drivers
- **THEN** `worst_case_chain` has no lanes, nodes or edges

#### Scenario: Contract
- **WHEN** the schema is exported
- **THEN** the TypeScript types include `worst_case_chain` and the contract check passes
