## Purpose

Which worker activities the screening evaluates for a facility, with the EPA ChemSTEER default parameters of each, and how a chemical outside ChemSTEER's preferred volatility range is treated, so that the source term is what a worker's task generates and not the facility's annual release.

## ADDED Requirements

### Requirement: A configured catalogue of worker activities
The system SHALL hold in configuration a catalogue of worker activities. Each activity SHALL state its label, its vapor generation model (AP-42 loading, penetration or mass transfer coefficient), whether it is indoor or outdoor, its hours per day, and the parameters of its model for a typical and a worst-case output, all taken from the EPA ChemSTEER User Guide defaults: drums of 55 gal at 20 containers/h and tank trucks of 5,000 gal at 2 containers/h with their saturation factors (drums 0.5 typical and 1 worst case; tank trucks 1); liquid sampling with an opening of 2.53 cm typical and 10 cm worst case at 100 ft/min for 1 h/day; equipment cleaning of multiple vessels with a 92 cm opening at 440 ft/min for 4 h/day. An unloading activity SHALL use the parameters of the matching loading activity. An activity added or changed in the configuration SHALL take effect with no code change.

#### Scenario: Catalogue entry
- **WHEN** the drum loading activity is read
- **THEN** it gives 55 gal, 20 containers/h, saturation factor 0.5 typical and 1 worst case, indoor

#### Scenario: New activity
- **WHEN** an activity is added to the configuration with one of the three models
- **THEN** it is evaluated for the facilities mapped to it, with no code change

#### Scenario: Invalid entry
- **WHEN** an activity names an unknown model or omits a parameter its model needs
- **THEN** loading the configuration raises an error that names the activity

### Requirement: Activities chosen from the industry's generic scenario and the TRI life cycle stage
The system SHALL choose the activities of a facility by this walk: the facility's primary NAICS code gives its CDR industrial sector (the existing crosswalk); the sector, with each TSCA life cycle stage the facility's Form R activity flags give (Manufacturing, Processing, Industrial use), gives the EPA generic scenario or OECD emission scenario document for that industry and the worker activities it describes, through a bundled crosswalk in which every row names its document. For each of its stages a facility SHALL always get the activities of the configured ChemSTEER generic operation of that stage (Manufacturing handles the product; Processing and Industrial use handle the raw material), and SHALL also get the activities of every crosswalk row of its sector and that stage, so a scenario document adds activities and never removes one. The activities of a facility SHALL be the union over its stages and rows. The result SHALL name the routes of each stage: the generic operation, and the title and document of every scenario row that applied. A facility with no stage (no activity flag) SHALL have no modelled activity, with the reason; a sector SHALL never be inferred and a scenario SHALL never be assigned to a sector without a row.

#### Scenario: Sector with a generic scenario
- **WHEN** a facility's sector and stage have a row in the crosswalk
- **THEN** the activities of the generic operation of that stage and those of the row are evaluated, each once, and the result names the generic operation and the scenario with its document

#### Scenario: Sector without a generic scenario
- **WHEN** the facility's sector has no row for its stage
- **THEN** only the activities of the ChemSTEER generic operation of that stage are evaluated and the result says no scenario document applied

#### Scenario: No sector
- **WHEN** the facility's NAICS code maps to no CDR sector
- **THEN** the generic operation of each of its stages is used and the result says no sector was found

#### Scenario: Several stages
- **WHEN** a facility manufactures and processes the chemical and the two stages share an activity
- **THEN** each activity is evaluated once and both routes are named

#### Scenario: No flags
- **WHEN** the facility's submission carries no activity flag
- **THEN** no activity is evaluated and the reason says the facility reported no activity

#### Scenario: Unknown activity in the crosswalk
- **WHEN** a crosswalk row names an activity that is not in the catalogue
- **THEN** loading the crosswalk raises an error that names the row

### Requirement: Typical and worst-case result per activity
For each activity the system SHALL compute a typical and a worst-case result: the vapor generation rate in g/s from the activity's model with the chemical's molecular weight in g/mol and vapor pressure in torr at 298 K and a vapor pressure correction factor of 1 (the pure chemical); the workplace concentration in mg/m^3, capped at saturation, from the two-zone model's near field for an indoor evaporation activity and from the mass balance with the ventilation and mixing factor of its setting for every other activity; and the 8-hour average from the activity's hours. A container activity, whose hours depend on a throughput TRI does not report, SHALL be taken as lasting the full 8 hours, stated as an assumption. The worst-case concentration SHALL be at least the typical one.

#### Scenario: Both outputs
- **WHEN** drum loading is evaluated for a chemical with a molecular weight and a vapor pressure
- **THEN** it has a typical and a worst-case generation rate, concentration and 8-hour average, and the worst case is the higher

#### Scenario: Indoor sampling uses the near field
- **WHEN** indoor liquid sampling is evaluated within the volatility range
- **THEN** its concentrations are the two-zone near-field averages over its hours, and its estimator says so

#### Scenario: Short task
- **WHEN** sampling lasts 1 h/day
- **THEN** its 8-hour average is one eighth of its concentration

#### Scenario: Pure chemical assumed
- **WHEN** any activity is evaluated
- **THEN** the result states that the pure chemical was assumed because TRI does not report its concentration in the material handled

### Requirement: Fail closed on missing chemical properties
An activity SHALL NOT be computed without the chemical's molecular weight and vapor pressure; its quantities SHALL be null with a warning naming the missing property. No property SHALL be defaulted.

#### Scenario: No vapor pressure
- **WHEN** no source gave a usable vapor pressure
- **THEN** every activity's quantities are null and the warning says the vapor pressure is missing

### Requirement: Chemicals outside the preferred volatility range
The system SHALL treat the chemical's vapor pressure against ChemSTEER's preferred range (0.001 to 35 torr, configured). Below the range no vapor estimate SHALL be made and the result SHALL say that the chemical is too little volatile for a vapor model and that particulate exposure is not modelled. Above the range a loading or unloading activity SHALL be computed as within it. Above the range an evaporation activity (penetration or mass transfer coefficient model) SHALL take its 8-hour averages from the ECETOC TRA band estimate when that capability has one for the activity, and otherwise SHALL be computed as within the range, capped at saturation, with a warning that the evaporation model is outside its validated range and likely overestimates. Each activity SHALL say which estimator gave its values.

#### Scenario: Below the range
- **WHEN** the vapor pressure is 0.0001 torr
- **THEN** no activity is computed and the reason says the chemical is below the range of the vapor models and that dust is not modelled

#### Scenario: Loading above the range
- **WHEN** the vapor pressure is 95 torr and drum loading is evaluated
- **THEN** it is computed with the AP-42 Loading Model and capped at saturation, with no out-of-range warning

#### Scenario: Evaporation above the range with a band estimate
- **WHEN** the vapor pressure is 95 torr, sampling is evaluated and a band estimate exists for it
- **THEN** its 8-hour averages are the band estimate and its estimator is named as ECETOC TRA

#### Scenario: Evaporation above the range without a band estimate
- **WHEN** the vapor pressure is 95 torr, sampling is evaluated and no band estimate exists for it
- **THEN** its values come from the Penetration Model and the two-zone model, capped at saturation, and the warning says the evaporation model is outside its validated range

#### Scenario: Configured range
- **WHEN** the upper limit of the range is changed in the configuration
- **THEN** which chemicals are treated as above it changes with no code change

### Requirement: The driving activity
The activity with the highest worst-case 8-hour average SHALL be the facility's driving activity, and its typical and worst-case results SHALL be the facility's modelled baseline and worst-case results. Every evaluated activity SHALL be listed with its results, ordered by worst-case 8-hour average.

#### Scenario: Highest worst case drives
- **WHEN** drum loading has the highest worst-case 8-hour average of four activities
- **THEN** it is named the driving activity and the other three are listed after it

#### Scenario: One activity
- **WHEN** only one activity is evaluated
- **THEN** it is the driving activity
