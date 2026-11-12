## Purpose

A bundled summary of the personal air samples in OSHA's Chemical Exposure Health Data, by substance and industry, so that the worker screening can rest on measured workplace concentrations where they exist, with no download during an assessment.

## ADDED Requirements

### Requirement: The summary is built from OSHA's published files by a script
A script SHALL build the summary from OSHA's Chemical Exposure Health Data yearly files for a configured window of years, with the file locations and the window in configuration. It SHALL keep only personal samples that are not blanks and whose result is a concentration in mg/m^3 or ppm, and SHALL reduce the samples of one sampling number and substance to one value, their average weighted by sampling time. For each substance (OSHA IMIS code), NAICS prefix of each configured length, and unit, it SHALL write the number of values, the number that are non-detects, the median, the 95th percentile, and the first and last year sampled. The summary SHALL record the window of years and the date it was built. The assessment SHALL NOT download these files.

#### Scenario: Personal samples only
- **WHEN** a file holds personal, area, bulk and wipe samples
- **THEN** only the personal samples enter the summary

#### Scenario: Several samples in one assessment
- **WHEN** one sampling number has two samples of a substance of 240 minutes each
- **THEN** they contribute one value, their time-weighted average

#### Scenario: Units kept apart
- **WHEN** a substance has results in ppm and in mg/m^3
- **THEN** each unit has its own row and no result is converted by the script

#### Scenario: Malformed row
- **WHEN** a row has a non-numeric result, an unknown unit code or no sampling time
- **THEN** it is skipped and counted in the script's report, and the build does not stop

#### Scenario: No download at run time
- **WHEN** an assessment runs
- **THEN** it reads the bundled summary and requests nothing from OSHA

### Requirement: A chemical is matched by CAS number through a bundled crosswalk
The system SHALL find a chemical's OSHA substance through a bundled crosswalk from OSHA IMIS substance code to CAS number built from OSHA's own substance list. A chemical whose CAS number is not in the crosswalk SHALL have no monitoring data, with that reason; a substance SHALL NOT be matched by name.

#### Scenario: Known chemical
- **WHEN** the chemical's CAS number is in the crosswalk
- **THEN** its IMIS code is used to read the summary

#### Scenario: Unknown chemical
- **WHEN** the chemical's CAS number is not in the crosswalk
- **THEN** no monitoring data is returned and the reason says OSHA's data has no substance with that CAS number

### Requirement: Lookup by industry with a minimum number of samples
The system SHALL look up a chemical for a facility by the facility's primary NAICS code, trying the most specific configured prefix first and then shorter ones down to a configured minimum length, and SHALL use the first level that has at least a configured minimum number of values. It SHALL return that level, the number of values and of non-detects, the median and the 95th percentile in mg/m^3 (a ppm row converted with the chemical's molecular weight and the configured molar volume), the years covered and the source. When both units have rows at the level it SHALL use the unit with more values and say so. When no level has enough values it SHALL return no monitoring data with the reason and the number found. A median that is a non-detect SHALL be reported as below detection, not as zero.

#### Scenario: Specific industry has enough
- **WHEN** the six-digit NAICS has at least the minimum number of values
- **THEN** the six-digit level is used

#### Scenario: Falls back to a broader industry
- **WHEN** the six-digit NAICS has too few values and the four-digit prefix has enough
- **THEN** the four-digit level is used and the result says so

#### Scenario: Too few everywhere
- **WHEN** no level down to the minimum length has enough values
- **THEN** no monitoring data is returned and the reason gives the number found

#### Scenario: ppm row
- **WHEN** the row used is in ppm and the molecular weight is known
- **THEN** the median and 95th percentile are returned in mg/m^3

#### Scenario: ppm row without a molecular weight
- **WHEN** the row used is in ppm and the molecular weight is missing
- **THEN** no monitoring data is returned and the reason names the molecular weight

#### Scenario: Median below detection
- **WHEN** more than half of the values are non-detects
- **THEN** the median is null with the reason "below detection" and the 95th percentile is still given

### Requirement: The limits of the data are stated
Every monitoring result SHALL state that the samples come from OSHA inspections of the industry, not from the facility assessed; that inspections are targeted and so are not a representative sample; the years covered; and the number of values and non-detects.

#### Scenario: Statement present
- **WHEN** a monitoring result is returned
- **THEN** it carries those statements
