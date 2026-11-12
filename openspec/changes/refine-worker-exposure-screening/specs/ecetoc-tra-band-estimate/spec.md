## Purpose

The ECETOC Targeted Risk Assessment tier-1 worker inhalation estimate, by process category and volatility band, which gives an exposure estimate for evaporation tasks of very volatile chemicals where the EPA evaporation equations are outside their validated range.

## ADDED Requirements

### Requirement: Bundled table from the published source
The system SHALL hold a bundled table of the ECETOC TRA worker inhalation initial estimates for industrial settings without local exhaust ventilation, in ppm, by process category (PROC) and volatility band, and of the TRA exposure duration modifiers, with the edition of the source in the file. Every value SHALL be the one printed in the cited ECETOC source; none SHALL be estimated. The table's location and the volatility band limits SHALL come from configuration.

#### Scenario: Value from the source
- **WHEN** a value of the table is compared with the cited ECETOC source
- **THEN** they are equal

#### Scenario: Missing file
- **WHEN** the table cannot be read
- **THEN** loading it raises an error that names the file

### Requirement: Estimate for an activity
The system SHALL give, for an activity mapped in configuration to a process category and a chemical with a vapor pressure and a molecular weight, the band the vapor pressure falls in and the estimate in mg/m^3 (the ppm value times the molecular weight over the configured molar volume): a worst-case 8-hour average with no duration modifier, and a baseline 8-hour average with the duration modifier of the activity's hours per day. An activity with no mapped process category, or a process category and band with no value in the table, SHALL have no estimate, with the reason.

#### Scenario: High volatility
- **WHEN** the vapor pressure falls in the high band and the activity's process category has a value for it
- **THEN** the worst-case average is that value converted to mg/m^3 and the baseline is it times the duration modifier of the activity's hours

#### Scenario: Unmapped activity
- **WHEN** the activity has no process category in the configuration
- **THEN** no estimate is returned and the reason says so

#### Scenario: No molecular weight
- **WHEN** the molecular weight is missing
- **THEN** no estimate is returned and the reason names it

### Requirement: The estimate is labelled as a banded tier-1 value
An estimate SHALL state that it is an ECETOC TRA tier-1 value for a process category and volatility band, not specific to the chemical beyond its band nor to the facility, and that no local exhaust ventilation or protective equipment was assumed.

#### Scenario: Statement present
- **WHEN** a band estimate is used for an activity
- **THEN** the activity carries that statement, the process category and the band
