## MODIFIED Requirements

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

### Requirement: Receptors of a worker scenario
A worker scenario SHALL name the workers of the driving facility as its receptors, with the activity, its hours per day, the working days and the tenure the model used, and SHALL NOT list residents.

#### Scenario: Workers
- **WHEN** the worker scenario is shown
- **THEN** its receptors are the facility's workers with the activity and the exposure schedule used
