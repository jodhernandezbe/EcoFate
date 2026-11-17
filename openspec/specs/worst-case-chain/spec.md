# worst-case-chain Specification

## Purpose

The run-wide worst-case exposure chain: one graph for the whole assessment run, with one lane per exposure pathway holding only the branch behind that pathway's worst case. It names no facility, so the user can see how the worst exposure of each route arises without choosing or identifying a facility.

## Requirements

### Requirement: One worst-case lane per pathway
The system SHALL build one worst-case chain for the run: one shared source node, then one lane per registered pathway, in the order of the lane registry. Each lane SHALL be taken from one facility only: the facility that drives the pathway's headline quantity in the scenario drivers. The headline quantity of each pathway SHALL come from configuration (hazard quotient for outdoor air, limit ratio for indoor air). A lane SHALL never mix values from different facilities or stacks. Different lanes MAY come from different facilities. A pathway with no driver SHALL be drawn as an unavailable lane with the configured reason.

#### Scenario: Different drivers
- **WHEN** facility A has the highest hazard quotient and facility B has the highest limit ratio
- **THEN** the outdoor-air lane carries only A's values, the indoor-air lane carries only B's values, and neither lane names either facility

#### Scenario: No worker result in the run
- **WHEN** no facility has an occupational result
- **THEN** the indoor-air lane is unavailable with the configured reason and the outdoor-air lane is drawn

#### Scenario: Empty run
- **WHEN** the run has no scenario drivers
- **THEN** the chain has no lanes and no nodes

### Requirement: Only the branch behind the worst value
Each lane SHALL keep only the branch that produces its worst value. In the outdoor-air lane that is the stack named by the driver (no other stack) and one receptor node for the age band with the highest dose the tool reported. That receptor node SHALL also list the band's share of residents and the total residents and radius. In the indoor-air lane that is the driving activity, or the OSHA monitoring evidence, with the worst-case ventilation values only; baseline values SHALL be left out. The endpoint SHALL carry the lane's headline quantity and its band, plus the lane's other quantities from the same facility (for example the cancer risk), each as that facility reported it.

#### Scenario: Several stacks
- **WHEN** the driving facility has three evaluated stacks and stack 2 gives the worst hazard quotient
- **THEN** the lane has one release node, for stack 2

#### Scenario: Several age bands
- **WHEN** the driving facility has residents in four age bands
- **THEN** the lane has one receptor node, for the band with the highest dose, with its dose and share

#### Scenario: Worker baseline left out
- **WHEN** the driving facility's worker result has worst-case and baseline values
- **THEN** the lane carries the worst-case values only

#### Scenario: Other quantity driven elsewhere
- **WHEN** the cancer risk is driven by a different facility from the hazard quotient
- **THEN** the outdoor-air endpoint shows the HQ driver's own cancer risk and a configured note that another facility in the run has a higher value of it, without naming that facility

### Requirement: No facility is identified
The chain SHALL NOT carry any facility's name, FRS ID, document control number, address, city, state, ZIP code, coordinates or industry, in any node title, fact, quantity source, warning or note. The shared source node SHALL be titled with configured text and carry the chemical's CAS number and name only. Each lane's release node SHALL carry the release quantities of its own facility (stack release and emission rate, or the activity's generation rate) with their units and sources.

#### Scenario: Source node
- **WHEN** the chain is built
- **THEN** the source node's title is the configured text, its facts are the CAS number and the chemical name, and it has no location or industry

#### Scenario: A step title that quotes the facility
- **WHEN** a step's title (for example the driving activity's label) contains the facility's name
- **THEN** the step carries the configured withheld title instead

#### Scenario: Leak check
- **WHEN** the chain is serialised for a run whose facilities have names and addresses
- **THEN** no facility name, FRS ID or address appears anywhere in the serialised chain

### Requirement: Most affected residents without their location
In the outdoor-air lane, the receptor node SHALL also carry what the driving facility's community scenario reported about its most affected residents. For each most affected tract, that is its residents, its distance in m and its fraction of the maximum, as the scenario holds them. When the scenario lists no tract, the node SHALL carry the scenario's receptors note (for example that no resident lives where the maximum falls). The node SHALL NOT carry a tract's label or GEOID, coordinates or bearing, because these locate the facility. The scenario's notes SHALL be added to the endpoint's warnings.

#### Scenario: Residents at the maximum
- **WHEN** the driving scenario lists two most affected tracts
- **THEN** the receptor node carries each tract's residents, distance and fraction of the maximum, and no tract label or coordinates

#### Scenario: Nobody there
- **WHEN** the driving scenario lists no tract and gives a receptors note
- **THEN** the receptor node carries that note

### Requirement: Values as the tools reported them
Every quantity in the chain SHALL carry its value as the tools reported it, its unit and its source, or no value and a reason. No value SHALL be computed, converted, summed or estimated to build the chain. Choosing a branch (the driver's stack, the band with the highest reported dose) is a selection, not a computation. Fixed text, labels and units SHALL come from configuration.

#### Scenario: Absent quantity
- **WHEN** the driving facility reported no cancer risk
- **THEN** the endpoint's cancer risk has no value and carries the reason

#### Scenario: Absent band dose
- **WHEN** no band dose was reported
- **THEN** the lane has the single "residents" receptor node with the reason, and no band is chosen
