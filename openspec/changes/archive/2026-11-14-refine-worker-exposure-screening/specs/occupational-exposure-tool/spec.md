## MODIFIED Requirements

### Requirement: Occupational result for each assessed facility
The system SHALL provide, for each facility the assessment evaluates, an `occupational_exposure` result with: the evidence its headline rests on; the inputs used (the chemical's molecular weight and vapor pressure with their sources, operating days per year, the benchmark and its source, RfC and IUR); for a baseline and a worst case the 8-hour TWA, the limit ratio, the worker hazard quotient, the worker cancer risk and the screening band; the driving activity and every evaluated activity with its own values; the monitoring summary or the reason there is none; and the warnings. The band of the result SHALL be the baseline band. The ambient result SHALL NOT change.

#### Scenario: Both tiers
- **WHEN** a facility has activities, chemical properties and a limit
- **THEN** the result holds the baseline and worst-case values, and the worst-case TWA is at least the baseline one

#### Scenario: Activities listed
- **WHEN** four activities are evaluated
- **THEN** the result names the driving one and lists all four with their values

#### Scenario: Ambient unchanged
- **WHEN** the occupational result is computed
- **THEN** the community concentration, hazard quotient and cancer risk equal what they were before

### Requirement: Fail closed on missing inputs
The system SHALL return null for every quantity that needs an input it does not have, with a warning naming it: no activity (the facility reported no activity flag) or no molecular weight or vapor pressure gives null modelled values; no benchmark gives a null ratio; no RfC or IUR gives a null hazard quotient or cancer risk; no operating days gives a null hazard quotient and cancer risk while the 8-hour TWA and the ratio are still computed. When neither monitoring data nor a model is available every value and the band SHALL be null. A value SHALL never be zero or "low" because an input is missing.

#### Scenario: No activity and no monitoring data
- **WHEN** the facility reported no activity flag and OSHA's data has too few samples
- **THEN** the values and the band are null and the warnings give both reasons

#### Scenario: No benchmark
- **WHEN** PubChem gave no TWA limit
- **THEN** the ratio is null, the hazard quotient and cancer risk are still computed, and the warning says the limit is missing

#### Scenario: No schedule
- **WHEN** the operating days could not be derived
- **THEN** the TWA and the ratio are computed, the hazard quotient and cancer risk are null, and the warning names the schedule

#### Scenario: No fugitive release
- **WHEN** the facility has no AIR FUG row
- **THEN** the worker values are computed as for any other facility

#### Scenario: Reported zero
- **WHEN** the fugitive release is reported as 0 kg/yr
- **THEN** the worker values are computed as for any other facility, not set to zero

### Requirement: Assumptions are visible
The result SHALL state that it is a screening indicator and not an OSHA compliance determination; which evidence its headline rests on; for a modelled result, that the activities are those of the generic scenario of the facility's industry and life cycle stage (or of ChemSTEER's generic operation) and not observed at the facility, that the pure chemical is assumed, that a container activity is taken as lasting the full shift, that the ventilation tiers are EPA ChemSTEER defaults and not the plant's, and that no local exhaust ventilation or protective equipment is assumed; and that dermal and particulate exposure are not modelled.

#### Scenario: Statement present
- **WHEN** an occupational result is returned
- **THEN** its warnings or assumptions carry those statements

### Requirement: Volatility context from the chemical's vapor pressure
The system SHALL use the chemical's vapor pressure in mmHg at about 25 degC and its molecular weight in g/mol, with their sources (by the existing source order), as inputs of the worker model, taken from the properties already resolved for the chemical and never looked up again per facility, and SHALL report both beside the result. It SHALL report where the vapor pressure falls against the configured preferred range of the vapor models (below, within or above). A missing vapor pressure or molecular weight SHALL give a null value with its reason, never a default.

#### Scenario: Volatile chemical
- **WHEN** the vapor pressure is within the configured range
- **THEN** it is reported with its source as within the range and the activities are modelled with it

#### Scenario: Above the range
- **WHEN** the vapor pressure is above the configured range
- **THEN** the result says so and each activity names the estimator that gave its values

#### Scenario: Non-volatile chemical
- **WHEN** the vapor pressure is below the configured range
- **THEN** the result says the chemical is below the range of the vapor models and no activity is modelled

#### Scenario: CompTox lacks it
- **WHEN** CompTox has no vapor pressure and PubChem has a clear one
- **THEN** the PubChem value is used and its source says PubChem

#### Scenario: Neither source has it
- **WHEN** no source has a usable vapor pressure
- **THEN** the value is null with the reason and no activity is modelled

#### Scenario: Configured threshold
- **WHEN** a limit of the preferred range is changed in the configuration
- **THEN** which chemicals are below, within or above it changes with no code change

### Requirement: The assistant is told how to read it
The description of the assessment tool SHALL say what the occupational result is, that it is a worker screening indicator distinct from the community result, which evidence it can rest on and in what order (measured OSHA samples of the industry, then the activity model, with a band estimate for evaporation tasks of very volatile chemicals), how the baseline and worst case and the bands read, that the TRI fugitive release is context and not an input, and that a null must be reported as not computed.

#### Scenario: Description
- **WHEN** the tool description is read
- **THEN** it covers those points and names no call order

### Requirement: The configuration behind the worst-case ratio
The worker result SHALL carry for the baseline and the worst case of the driving activity the setting (indoor or outdoor), airflow (m^3/s) and mixing factor, the vapor generation rate (g/s), the workplace concentration, whether the saturation cap applied, the 8-hour average, limit ratio, hazard quotient, cancer risk and band, and SHALL carry the activity's label, model, hours per day and estimator, the working days per year used, and the occupational limit with its source, so that the worker scenario can be stated without further computation.

#### Scenario: Both tiers carry their configuration
- **WHEN** the worker result is read
- **THEN** the baseline and the worst case each state their airflow, mixing factor and generation rate beside their values

#### Scenario: No limit
- **WHEN** the chemical has no occupational limit
- **THEN** the limit ratio is absent, the other quantities are still given, and the reason is carried

## ADDED Requirements

### Requirement: Evidence hierarchy
The headline baseline and worst-case values of the worker result SHALL rest on the best evidence available, in this order: measured data, when the OSHA monitoring capability returns a result for the chemical and the facility's industry (the median as the baseline 8-hour average and the 95th percentile as the worst case); otherwise the driving activity of the model. The result SHALL name its evidence ("monitoring", "activity_model" or none) and SHALL always carry the modelled activities beside a measured headline, so that the two can be compared. When the measured median is below detection the baseline SHALL be null with that reason and the band SHALL be taken from the worst case, stated in a warning. The limit ratio, hazard quotient, cancer risk and band SHALL be computed from the headline values in the same way whatever the evidence.

#### Scenario: Monitoring data exists
- **WHEN** OSHA's data has enough personal samples for the chemical in the facility's industry
- **THEN** the evidence is "monitoring", the baseline is the median, the worst case is the 95th percentile, and the modelled activities are still listed

#### Scenario: No monitoring data
- **WHEN** OSHA's data has too few samples and activities can be modelled
- **THEN** the evidence is "activity_model" and the headline is the driving activity

#### Scenario: Median below detection
- **WHEN** the measured median is below detection
- **THEN** the baseline is null with that reason and the band comes from the 95th percentile, with a warning

#### Scenario: Neither
- **WHEN** there is no monitoring data and no activity can be modelled
- **THEN** the evidence is none and every value is null with the reasons

### Requirement: The fugitive release is context only
The result SHALL carry the facility's TRI fugitive air release in kg/yr and its reporting year as reported context, with a statement that it is the mass released from the site to air other than through stacks and is not used to compute a worker value. No worker quantity SHALL depend on it.

#### Scenario: Same result with or without it
- **WHEN** two facilities differ only in their fugitive release
- **THEN** their worker values and bands are equal

#### Scenario: Shown as context
- **WHEN** a facility reports a fugitive release
- **THEN** the result carries it with its year and the statement
