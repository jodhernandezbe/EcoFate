## Purpose

Defines the worst-case scenario of an exposure pathway: the combination of factors (source, release, conditions, receptors) that produces the high-end value of a result and, where that value exceeds a level of concern, is the evidence of the combination that gives rise to the risk. The definition is the same for every pathway, current or future, so a new pathway adds a scenario without changing how scenarios are stated or shown.

## Requirements

### Requirement: One generic scenario for every pathway
A worst-case scenario SHALL be stated in one shape for every exposure pathway: the pathway (medium, route and receptor class, e.g. outdoor air, inhalation, general population), the result quantity with its unit and high-end value, the benchmark and the screening band it falls in (as the assessment reported them), the facility, a list of factors, and a list of receptors. Each factor SHALL have a name, a group (source, release, conditions or receptor model), a value, a unit and where it came from, or be absent with a reason. A scenario SHALL contain only values a tool returned; nothing SHALL be estimated for it. The shape SHALL NOT depend on the pathway: the community inhalation scenario and the worker inhalation scenario SHALL use it, and so SHALL any pathway added later.

#### Scenario: Community inhalation
- **WHEN** a facility has three evaluated stacks and stack 2 gives the highest hazard quotient
- **THEN** the scenario of outdoor air, inhalation, general population names stack 2 among its source factors, the release factors, and the stability, wind speed, distance and plume height among its conditions

#### Scenario: Worker inhalation
- **WHEN** a facility's worker result rests on the activity model
- **THEN** the scenario of indoor air, inhalation, worker lists the driving activity, its vapor generation model and rate, the chemical's vapor pressure and molecular weight, the ventilation (airflow and mixing factor), whether the saturation cap applied, and the activity's hours

#### Scenario: Worker inhalation from monitoring
- **WHEN** a facility's worker result rests on OSHA monitoring data
- **THEN** the scenario lists the evidence, the industry level used, the number of samples and non-detects, the years covered and the 95th percentile

#### Scenario: An absent factor
- **WHEN** no tool reported a factor, such as a stack dimension
- **THEN** the factor is listed as absent with its reason, and the scenario is still stated

#### Scenario: No cancer risk
- **WHEN** the chemical has no unit risk
- **THEN** no cancer risk scenario is stated and the reason is given

### Requirement: Scenarios are produced by a registry of pathways
Each pathway that has results SHALL produce its scenarios through one entry of a registry of pathways. Adding a pathway SHALL be done by adding one entry (its factors, its quantities and how its receptors are found) and its configuration, without changing the scenario shape, the workspace projection or the display code. A pathway whose results are absent SHALL produce no scenario and SHALL be listed with the reason.

#### Scenario: A pathway is added
- **WHEN** a new pathway entry is registered
- **THEN** its scenarios reach the workspace and the dashboard in the same shape, with no change to the display code

#### Scenario: Pathway without results
- **WHEN** a pathway has no result for any assessed facility
- **THEN** no scenario is produced for it and the reason is stated

### Requirement: The driver and the level of concern
For each pathway and quantity the system SHALL identify the assessed facility whose scenario has the highest value, and SHALL list the other facilities after it, ordered by value. Facilities screened out or not assessed SHALL NOT be drivers. A scenario SHALL carry the screening band its value falls in ("high", "moderate" or "low"), computed by the shared band definition from that quantity alone. The system SHALL NOT state that a risk is unreasonable or that a determination was made: the scenario reports the combination of factors behind a screening value and its band, as evidence for a reader to weigh.

#### Scenario: Two facilities
- **WHEN** two facilities are assessed and the second has the higher value of a quantity
- **THEN** the second is the driver of that quantity

#### Scenario: Band of a scenario
- **WHEN** a community hazard quotient scenario has the value 0.4
- **THEN** it carries the band "moderate" and its factors, and no wording of a regulatory finding

#### Scenario: Value above the level of concern
- **WHEN** a scenario's value is at or above the upper boundary of its quantity
- **THEN** it carries the band "high" and its factors, and no wording of a regulatory finding

#### Scenario: Same words for both pathways
- **WHEN** a community and a worker scenario are both in the upper band
- **THEN** both carry the band "high"

### Requirement: Receptors of a community scenario
A scenario whose receptors are residents SHALL list the census tracts around the facility ranked by the concentration the scenario's own configuration (stability, wind speed, stack and emission rate) gives at each tract's distance, with each tract's residents, age mix, distance, bearing and the coordinates of its internal point as the population tool reported them. A receptor SHALL be listed as most affected when its concentration is at least a configured fraction of the scenario's maximum, up to a configured number of tracts. A tract outside the dispersion model's range of distances SHALL NOT be ranked and the scenario SHALL say how many were not. When no tract reaches the fraction the scenario SHALL say that no resident lives where the maximum falls, with the nearest populated tract and its fraction of the maximum, and SHALL NOT show an empty receptor list without that reason.

#### Scenario: Residents near the maximum
- **WHEN** a tract's internal point lies at the distance of the maximum
- **THEN** it is listed first, with a concentration equal to the maximum, its residents, age mix, distance and bearing

#### Scenario: Nobody there
- **WHEN** no tract reaches the configured fraction of the maximum
- **THEN** the scenario says no resident lives where the maximum falls and names the nearest populated tract

#### Scenario: Ranked by concentration
- **WHEN** two tracts are listed
- **THEN** the one with the higher concentration at its distance comes first

#### Scenario: Tract outside the model range
- **WHEN** a tract lies closer than the model's smallest distance
- **THEN** it is not ranked and the scenario counts it

### Requirement: Receptors of a worker scenario
A worker scenario SHALL name the workers of the driving facility as its receptors, with the activity, its hours per day, the working days and the tenure the model used, and SHALL NOT list residents.

#### Scenario: Workers
- **WHEN** the worker scenario is shown
- **THEN** its receptors are the facility's workers with the activity and the exposure schedule used
