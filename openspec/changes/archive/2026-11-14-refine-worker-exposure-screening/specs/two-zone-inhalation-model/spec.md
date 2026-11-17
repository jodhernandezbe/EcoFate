## Purpose

The EPA/OPPT Near-Field/Far-Field Inhalation Exposure Model, which estimates the concentration in the air a worker breathes beside an open source separately from the rest of the room, used for indoor open-surface worker activities.

## ADDED Requirements

### Requirement: Near-field and far-field time-weighted concentrations
The system SHALL compute, from a vapor generation rate G in g/s, an activity duration h in hours, a near field of length, width and height in m, a near-field air speed in m/h, a far-field volume VFF in m^3 and an air exchange rate AER per hour, the near-field and the far-field concentrations in mg/m^3 averaged over the duration, starting from zero concentration, with the equations of the EPA ChemSTEER User Guide: the free surface area FSA = 2 x (L x H) + 2 x (W x H) + (L x W), the near-field ventilation QNF = 0.5 x FSA x air speed and the far-field ventilation QFF = VFF x AER, both in m^3/h. It SHALL reject a non-finite input, a negative generation rate and a non-positive duration, dimension, air speed, volume or exchange rate with a `ValueError`.

#### Scenario: Long activity tends to steady state
- **WHEN** the duration is long compared with the room's air turnover
- **THEN** the near-field average approaches G x 3,600,000 x (1/QFF + 1/QNF) mg/m^3 and the far-field average approaches G x 3,600,000 / QFF

#### Scenario: Near field is higher
- **WHEN** the generation rate is positive
- **THEN** the near-field average is greater than the far-field average

#### Scenario: Proportional to generation
- **WHEN** only the generation rate is doubled
- **THEN** both averages are doubled

#### Scenario: Zero generation
- **WHEN** the generation rate is 0 g/s
- **THEN** both averages are 0 mg/m^3

#### Scenario: Invalid input
- **WHEN** the far-field volume is zero, the duration is negative or the generation rate is NaN
- **THEN** a `ValueError` is raised

### Requirement: Default geometry and rooms from the cited source
The near-field dimensions (3.05 m by 3.05 m by 1.83 m), the near-field air speed (360 m/h), and the low-end and high-end far-field volumes (300 and 2,000 m^3) and air exchange rates (2 and 15 per hour) SHALL come from configuration with the values of the EPA ChemSTEER User Guide, Tables B-11a to B-11c. The baseline SHALL use the high-end room and the worst case the low-end room.

#### Scenario: Worst case is higher
- **WHEN** both rooms are evaluated for one generation rate and duration
- **THEN** the worst-case near-field average is greater than the baseline one

#### Scenario: Configured room
- **WHEN** a room volume is changed in the configuration
- **THEN** the concentration changes with no code change
