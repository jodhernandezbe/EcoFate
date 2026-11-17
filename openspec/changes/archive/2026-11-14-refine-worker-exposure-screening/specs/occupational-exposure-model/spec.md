## MODIFIED Requirements

### Requirement: Workplace box-model concentration
The system SHALL compute the workplace concentration in mg/m^3 as the vapor generation rate of a worker activity in g/s times 1,000 over the ventilation rate in m^3/s times the mixing factor (the EPA/OPPT Mass Balance Inhalation Model), and SHALL cap it at the chemical's saturation concentration in mg/m^3, reporting whether the cap applied. It SHALL reject a non-finite or negative generation rate or saturation concentration, a non-positive ventilation rate or mixing factor, and a mixing factor above 1, with a `ValueError`. The generation rate SHALL NOT be derived from an annual release.

#### Scenario: Worked example
- **WHEN** the generation rate is 0.01 g/s, the ventilation is 1.416 m^3/s, the mixing factor 0.5 and the saturation concentration is far higher
- **THEN** the concentration is 10 mg/s over 0.708 m^3/s and the cap did not apply

#### Scenario: Doubled release
- **WHEN** the generation rate is doubled and nothing else changes, below saturation
- **THEN** the concentration is doubled

#### Scenario: Smaller ventilation
- **WHEN** only the ventilation rate or the mixing factor is lowered, below saturation
- **THEN** the concentration is higher

#### Scenario: Capped at saturation
- **WHEN** the mass balance gives 5,000 mg/m^3 and the saturation concentration is 1,200 mg/m^3
- **THEN** the concentration is 1,200 mg/m^3 and the result says the cap applied

#### Scenario: Invalid input
- **WHEN** the ventilation rate is zero, the mixing factor is 1.5 or the generation rate is NaN
- **THEN** a `ValueError` is raised

### Requirement: Two ventilation tiers
The system SHALL evaluate the mass balance for a baseline (typical) tier and a worst-case tier whose ventilation rates and mixing factors come from configuration and depend on whether the activity is indoor or outdoor, with the EPA ChemSTEER defaults: indoor 3,000 ft^3/min and 0.5 baseline, 500 ft^3/min and 0.1 worst case; outdoor 237,600 ft^3/min and 0.5 baseline, and 26,400 x (60 x vz / 5,280) ft^3/min and 0.1 worst case, where vz is the activity's air speed in ft/min (440 ft/min when its model has none). It SHALL convert ft^3/min to m^3/s with the shared unit conversion and SHALL return both tiers with the values used.

#### Scenario: Worst case is higher
- **WHEN** both tiers are evaluated for one generation rate, below saturation
- **THEN** the worst-case concentration is greater than the baseline one

#### Scenario: Outdoor worst case
- **WHEN** an outdoor activity has an air speed of 440 ft/min
- **THEN** its worst-case ventilation is 132,000 ft^3/min

#### Scenario: Configured tiers
- **WHEN** a tier's ventilation rate is changed in the configuration
- **THEN** its concentration changes with no code change

### Requirement: Eight-hour TWA and limit ratio
The system SHALL compute the 8-hour time-weighted average in mg/m^3 as the workplace concentration times the smaller of the activity's hours per day and 8, over 8, and the limit ratio as that average over the occupational exposure limit in mg/m^3, rejecting a non-positive limit.

#### Scenario: Long shift is capped
- **WHEN** the activity lasts 8 h/day or more
- **THEN** the TWA equals the workplace concentration

#### Scenario: Short shift is diluted
- **WHEN** the activity lasts 4 h/day
- **THEN** the TWA is half the workplace concentration

#### Scenario: Ratio
- **WHEN** the TWA is 0.5 mg/m^3 and the limit 5 mg/m^3
- **THEN** the ratio is 0.1

#### Scenario: Non-positive limit
- **WHEN** the limit is zero
- **THEN** a `ValueError` is raised

## REMOVED Requirements

### Requirement: Occupational risk tier
**Reason**: The tiers "exceedance", "elevated" and "acceptable" read as a compliance finding and were defined for workers only. They are replaced by the shared screening bands.
**Migration**: Use the `risk-bands` capability: "exceedance" becomes "high", "elevated" becomes "moderate" and "acceptable" becomes "low", and a quantity exactly on a boundary now falls in the higher band.
