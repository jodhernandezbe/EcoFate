## ADDED Requirements

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
