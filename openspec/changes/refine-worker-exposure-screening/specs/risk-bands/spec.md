## Purpose

The one definition of the screening bands "high", "moderate" and "low" and of their boundaries, shared by the worker and the community results so that both pathways are read in the same words.

## ADDED Requirements

### Requirement: Three screening bands with configured boundaries
The system SHALL classify a screening result into the band "high", "moderate" or "low" from up to three quantities: the hazard quotient, the lifetime cancer risk and, for workers, the ratio of the 8-hour average to the occupational limit. A quantity at or above its upper boundary SHALL give "high"; otherwise a quantity at or above its lower boundary SHALL give "moderate"; otherwise the band SHALL be "low". The band of a result SHALL be the highest band any of its quantities gives. The boundaries SHALL come from one configuration block used by every pathway (hazard quotient 0.1 and 1; cancer risk 1e-6 and 1e-4; limit ratio 0.1 and 1). A quantity that is null SHALL NOT count, and when every quantity is null the band SHALL be null, never "low".

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

### Requirement: Both pathways use the same bands
The community (outdoor air, general population) result and the worker result SHALL each carry a band computed by this capability from their own quantities. The words "exceedance", "elevated", "acceptable", "at or above threshold", "below threshold" and "near concern" SHALL NOT be used as the value or label of a band anywhere in a tool result, the workspace state or the interface.

#### Scenario: Community band
- **WHEN** a facility's worst-case community hazard quotient is 0.4 and it has no cancer risk
- **THEN** its community band is "moderate"

#### Scenario: Worker band
- **WHEN** a facility's worker limit ratio is 2
- **THEN** its worker band is "high"

#### Scenario: Old words are gone
- **WHEN** a tool result, the workspace state or the interface text is searched
- **THEN** none of the old tier words appears as a band

### Requirement: A band is a screening priority, not a finding
Every place that shows a band SHALL present it as a screening priority. The system SHALL NOT state that a limit is exceeded at the facility, that an exposure is acceptable or safe, or that a risk is unreasonable.

#### Scenario: Label
- **WHEN** a band is shown to a user
- **THEN** it reads "High", "Moderate" or "Low" screening priority, in words as well as colour

#### Scenario: No finding
- **WHEN** a result is in the band "high"
- **THEN** no text says the facility exceeds a limit or violates a standard
