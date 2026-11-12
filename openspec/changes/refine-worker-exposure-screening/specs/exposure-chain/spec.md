## MODIFIED Requirements

### Requirement: Diagram of worst-case connections
The tab SHALL draw, for the focused facility, a facility hub and one lane per registered pathway, each
lane running source, pathway, route, receptor and endpoint with a connection between consecutive steps.
Each connection SHALL be labelled with the quantity it carries and each node SHALL show its headline
value. Every value, name and status SHALL come from the API; the browser SHALL NOT compute, convert or
estimate any of them. A value the API did not report SHALL read "not reported" with its reason, never 0
or "-". With no facility the tab SHALL say what to do instead of drawing placeholders.

#### Scenario: Community lane
- **WHEN** the facility has a community result
- **THEN** the lane shows the stack release, outdoor air with the peak concentration and distance, inhalation, the residents counted with their age bands, and the worst-case hazard quotient and cancer risk

#### Scenario: Worker lane
- **WHEN** the facility has an occupational result
- **THEN** the lane shows the driving worker activity with its vapor generation rate (or the OSHA monitoring evidence), indoor or outdoor workplace air with ventilation and concentration, inhalation, the worker with the activity's hours and the working days, and the 8-hour average, limit ratio, benchmark source, hazard quotient, cancer risk and band

#### Scenario: Missing value
- **WHEN** a value is null (for example no vapor pressure)
- **THEN** that node or connection reads "not reported" with the reason and the rest of the diagram is unaffected

#### Scenario: Unavailable lane
- **WHEN** the facility lacks the result a lane needs
- **THEN** the lane is drawn as an empty, labelled lane saying why

#### Scenario: No facility
- **WHEN** the workspace has no facilities
- **THEN** the tab shows an empty state

### Requirement: Every state is checked visually
Each state of the tab (both lanes, missing values, unavailable lane, the "high" band, a worker lane resting on monitoring data, light and dark, wide and
narrow) SHALL be rendered in a real browser by the test suite, and its screenshot SHALL be compared with
the approved reference.

#### Scenario: Layout change
- **WHEN** a change moves or overlaps nodes
- **THEN** the screenshot comparison fails

### Requirement: Status in words and colour
Status SHALL be the screening band the API sent for both pathways ("high", "moderate" or "low"), shown
as the words "High", "Moderate" or "Low" as well as colour, with design-token colours that meet WCAG AA
in light and dark. The browser SHALL NOT relabel or recompute a band.

#### Scenario: Exceedance
- **WHEN** the occupational band is "high"
- **THEN** the endpoint and the lane's connections read "High" in words and use the high look

#### Scenario: Same look for both lanes
- **WHEN** the community and the worker endpoints are both "moderate"
- **THEN** both read "Moderate" and use the same look
