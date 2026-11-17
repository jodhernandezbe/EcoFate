## MODIFIED Requirements

### Requirement: Fugitive air release on the record
The system SHALL also read the TRI `AIR FUG` medium (a configured medium, one more query like the stack one, with the same year window, paging, throttling and validation) and put each facility's latest-year fugitive release, converted to kg/yr with the shared unit conversion, on its record as `fugitive_release_kg_per_year`, null when TRI has none. Fugitive rows SHALL NOT enter the stack emission rate. A facility with only a fugitive release SHALL be returned as a worker-only facility: marked as such, with no stack release and no emission rate, never listed as a stack source, and listed apart from the stack facilities. Worker-only facilities SHALL be capped by their own configured number, largest fugitive release first, and the number left out SHALL be reported.

#### Scenario: Both media
- **WHEN** a facility reports stack and fugitive air in the latest year
- **THEN** its record has the stack release as before and its fugitive release in kg/yr

#### Scenario: Stack only
- **WHEN** a facility has no fugitive row
- **THEN** the fugitive release is null

#### Scenario: Fugitive only
- **WHEN** a facility has a fugitive row but no stack row
- **THEN** it is returned as a worker-only facility with its fugitive release, and it is not among the stack sources

#### Scenario: Stack numbers unchanged
- **WHEN** worker-only facilities are added
- **THEN** every stack release and emission rate, and the list and count of stack sources, equal what they were

#### Scenario: Unconvertible unit
- **WHEN** a fugitive row's unit is not a mass
- **THEN** that release is null and a warning counts it

#### Scenario: More than the cap
- **WHEN** more worker-only facilities exist than the configured number
- **THEN** the largest are kept and the result says how many were left out
