## MODIFIED Requirements

### Requirement: Neighbours and workers are reasoned about together
The prompt SHALL explain, as assessment reasoning and without naming a tool or a call order, that people near a plant and people who work in it are exposed differently (a stack release reaches the neighbours through outdoor air; workers breathe the vapour their own tasks generate), that the community and the worker results are reported side by side with which one drives the concern at a facility, and that both are read in the same screening bands (high, moderate, low) which are priorities for further work and not findings. It SHALL explain that a worker figure rests on the best evidence available, measured samples of the industry before an activity model with generic ventilation, and that the answer says which; that the worker figures are a screening, not a compliance finding; that the site's fugitive release is not a measure of worker exposure; and that a worker figure that could not be computed is reported as not computed with its reason.

#### Scenario: Both audiences
- **WHEN** the prompt is read
- **THEN** it says to report the community and the worker result side by side and to say which drives the concern

#### Scenario: Bands are priorities
- **WHEN** the prompt is read
- **THEN** it says the bands are screening priorities and never that a limit is exceeded or an exposure acceptable

#### Scenario: Evidence named
- **WHEN** the prompt is read
- **THEN** it says to state whether a worker figure rests on measured samples or on a model

#### Scenario: Not a compliance finding
- **WHEN** the prompt is read
- **THEN** it says the worker figures are a screening, not a compliance finding

#### Scenario: Not computed
- **WHEN** the prompt is read
- **THEN** it says a worker figure that could not be computed is reported as not computed, with the reason
