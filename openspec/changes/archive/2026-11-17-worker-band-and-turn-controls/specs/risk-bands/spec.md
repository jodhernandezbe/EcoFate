## MODIFIED Requirements

### Requirement: Three screening bands with configured boundaries
The system SHALL classify a screening result into the band "high", "moderate" or "low" from up to three quantities: the hazard quotient, the lifetime cancer risk and, for workers, the ratio of the 8-hour average to the occupational limit. A quantity at or above its upper boundary SHALL give "high"; otherwise a quantity at or above its lower boundary SHALL give "moderate"; otherwise the band SHALL be "low". The band of a community result SHALL be the highest band its hazard quotient and cancer risk give. The band of a worker result SHALL be the higher of the bands its limit ratio and its cancer risk give; its hazard quotient, which compares the worker with a general-population reference concentration, SHALL set the band only when there is no occupational limit, and SHALL otherwise be reported as context. The boundaries SHALL come from one configuration block used by every pathway (hazard quotient 0.1 and 1; cancer risk 1e-6 and 1e-4; limit ratio 0.1 and 1). A quantity that is null SHALL NOT count, and when every quantity is null the band SHALL be null, never "low".

#### Scenario: High by one quantity
- **WHEN** the hazard quotient is 1.2 and the cancer risk is below 1e-6
- **THEN** the band is "high"

#### Scenario: Moderate by cancer risk
- **WHEN** the cancer risk is 5e-6 and the hazard quotient is below 0.1
- **THEN** the band is "moderate"

#### Scenario: On the boundary
- **WHEN** the hazard quotient is exactly 1
- **THEN** the band is "high"

#### Scenario: Low
- **WHEN** every quantity present is below its lower boundary
- **THEN** the band is "low"

#### Scenario: Nothing to compare
- **WHEN** every quantity is null
- **THEN** the band is null

#### Scenario: Configured boundary
- **WHEN** a boundary is changed in the configuration
- **THEN** the bands of both pathways change with no code change

#### Scenario: Worker hazard quotient with a limit
- **WHEN** a worker result has a limit ratio of 0.38, a hazard quotient of 32.6 and no cancer risk
- **THEN** its band is "moderate"

#### Scenario: Worker cancer risk with a limit
- **WHEN** a worker result has a limit ratio of 0.38 and a cancer risk of 0.001
- **THEN** its band is "high"

#### Scenario: Worker without a limit
- **WHEN** a worker result has no occupational limit and a hazard quotient of 2
- **THEN** its band is "high"
