## Purpose

The deterministic equations of EPA ChemSTEER that give the vapor generation rate of a worker activity (filling a container, an open liquid surface) and the saturation concentration of a chemical in air, which the worker screening uses as its source term and its physical ceiling.

## ADDED Requirements

### Requirement: Vapor generation from filling a container
The system SHALL compute the vapor generation rate in g/s of filling containers with the EPA/OAQPS AP-42 Loading Model: G = f x MW x (3785.4 x Vc) x r x X x (VP / 760) / (3600 x T x R), with the saturation factor f (unitless, in (0, 1]), the molecular weight MW in g/mol, the container volume Vc in gallons, the fill rate r in containers per hour, the vapor pressure correction factor X (unitless, in (0, 1]), the vapor pressure VP in torr, the temperature T in K and R = 82.05 atm cm^3/(mol K). It SHALL reject a non-finite input, a non-positive MW, Vc, r or T, a negative VP and an f or X outside (0, 1] with a `ValueError`.

#### Scenario: Formula
- **WHEN** f is 0.5, MW 100 g/mol, Vc 55 gal, r 20 containers/h, X 1, VP 10 torr and T 298 K
- **THEN** the rate equals 0.5 x 100 x (3785.4 x 55) x 20 x (10 / 760) / (3600 x 298 x 82.05) g/s

#### Scenario: Proportional to vapor pressure
- **WHEN** only the vapor pressure is doubled
- **THEN** the rate is doubled

#### Scenario: Invalid input
- **WHEN** the saturation factor is 1.5, the molecular weight is zero or the vapor pressure is NaN
- **THEN** a `ValueError` is raised

### Requirement: Vapor generation from an open liquid surface
The system SHALL compute the vapor generation rate in g/s of an open liquid surface of diameter d in cm and area A = pi x d^2 / 4 in cm^2 under an air speed vz in ft/min with two models. The EPA/OPPT Penetration Model, for air speeds at or below 100 ft/min: G = 8.24e-8 x MW^0.835 x X x VP x (1/29 + 1/MW)^0.25 x vz^0.5 x A / (T^0.05 x d^0.5 x P^0.5), with the pressure P in atm. The EPA/OPPT Mass Transfer Coefficient Model, for air speeds above 100 ft/min: G = 1.93e-7 x MW^0.78 x X x VP x (1/29 + 1/MW)^0.33 x vz^0.78 x A / (T^0.4 x d^0.11 x (T^0.5 - 5.87)^(2/3)). Each SHALL reject a non-finite input, a non-positive MW, d, vz, T or P, a negative VP and an X outside (0, 1] with a `ValueError`. The Penetration Model SHALL reject an air speed above 100 ft/min and the Mass Transfer Coefficient Model an air speed at or below 100 ft/min.

#### Scenario: Penetration formula
- **WHEN** MW is 100 g/mol, X 1, VP 10 torr, vz 100 ft/min, d 2.53 cm, T 298 K and P 1 atm
- **THEN** the rate equals the Penetration Model expression evaluated with those values

#### Scenario: Mass transfer formula
- **WHEN** MW is 100 g/mol, X 1, VP 10 torr, vz 440 ft/min, d 92 cm and T 298 K
- **THEN** the rate equals the Mass Transfer Coefficient Model expression evaluated with those values

#### Scenario: Larger opening
- **WHEN** only the diameter is increased
- **THEN** the rate is higher

#### Scenario: Wrong model for the air speed
- **WHEN** the Penetration Model is given 440 ft/min, or the Mass Transfer Coefficient Model 100 ft/min
- **THEN** a `ValueError` is raised

### Requirement: Saturation concentration
The system SHALL compute the saturation concentration of a chemical in air in mg/m^3 as 1,000,000 x X x VP / 760 (ppm) times MW over the molar volume (24.45 L/mol at 25 degC and 1 atm, configured), rejecting a non-finite input, a non-positive MW or molar volume, a negative VP and an X outside (0, 1].

#### Scenario: Formula
- **WHEN** VP is 76 torr, X 1 and MW 100 g/mol
- **THEN** the saturation concentration is 100,000 ppm x 100 / 24.45 mg/m^3

#### Scenario: Zero vapor pressure
- **WHEN** the vapor pressure is 0 torr
- **THEN** the saturation concentration is 0 mg/m^3

### Requirement: Constants are those of the cited source
Every constant of these equations SHALL be the value printed in the EPA ChemSTEER User Guide (updated May 2015), and each function SHALL name the model and the guide in its documentation with the unit of every argument and result.

#### Scenario: Traceable
- **WHEN** a constant of an equation is read
- **THEN** it equals the value in the cited guide and the documentation names the model
