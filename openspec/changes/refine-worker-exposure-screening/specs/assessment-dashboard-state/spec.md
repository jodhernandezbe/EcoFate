## MODIFIED Requirements

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

## ADDED Requirements

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
