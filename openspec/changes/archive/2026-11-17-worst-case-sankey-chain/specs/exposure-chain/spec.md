## MODIFIED Requirements

### Requirement: Diagram of worst-case connections
The tab SHALL draw the run's worst-case chain (`worst_case_chain`) as a Sankey diagram: one shared source node, then one lane per pathway, each running release, pathway, route, receptor and endpoint, with a band between consecutive steps. The tab SHALL NOT ask the user to choose a facility and SHALL NOT show any facility's name, identifier or location. Each band SHALL be labelled with the quantity it carries, and each node SHALL show its headline value. Every value, name and status SHALL come from the API; the browser SHALL NOT compute, convert or estimate any of them. A value the API did not report SHALL read "not reported" with its reason, never 0 or "-". With an empty chain, the tab SHALL say what to do instead of drawing placeholders.

#### Scenario: Community lane
- **WHEN** the run has a community result
- **THEN** the lane shows the stack behind the worst hazard quotient with its release, outdoor air with the peak concentration and distance, inhalation, the most exposed age band with its dose, and the worst-case hazard quotient and cancer risk

#### Scenario: Worker lane
- **WHEN** the run has an occupational result
- **THEN** the lane shows the driving worker activity with its vapor generation rate (or the OSHA monitoring evidence), workplace air with its worst-case ventilation and concentration, inhalation, the worker with the activity's hours and working days, and the 8-hour average, limit ratio, benchmark source and band

#### Scenario: No facility picker
- **WHEN** the run has several facilities
- **THEN** the tab shows one chain with no facility picker and no facility name

#### Scenario: Missing value
- **WHEN** a value is null (for example no vapor pressure)
- **THEN** that node or band reads "not reported" with the reason and the rest of the diagram is unaffected

#### Scenario: Unavailable lane
- **WHEN** the run lacks the result a lane needs
- **THEN** the lane is listed as unavailable with its reason, and no bands are drawn for it

#### Scenario: No facility
- **WHEN** no facility has been assessed (or the server sends no chain)
- **THEN** the tab shows an empty state

### Requirement: The diagram draws the graph the API sent
The diagram SHALL draw the chain exactly as sent, laid out by a Sankey layout in columns from left to right (source, release, pathway, route, receptor, endpoint), with any number of lanes and nodes. A new lane, node or edge in the graph SHALL be drawn without a frontend change. Bands SHALL have one fixed width, because the steps carry different units, and SHALL be coloured by their lane's screening band (neutral when the lane has none). The diagram SHALL fit the panel's width, scale with it, and scroll horizontally rather than shrink text below a legible size. Bands SHALL show the direction of flow, with a still marker when the user prefers reduced motion.

#### Scenario: New lane
- **WHEN** the graph contains a lane the frontend has never seen
- **THEN** it is drawn with its nodes and labelled bands

#### Scenario: Equal bands
- **WHEN** one band carries 1,000 kg/yr and the next carries 0.2 µg/m³
- **THEN** both bands are drawn at the same width

#### Scenario: Branches
- **WHEN** the graph has more than one node in a column (for example a new lane's extra receptor)
- **THEN** each is drawn and connected, without overlap

### Requirement: Every state is checked visually
Each state of the tab (both lanes, missing values, an unavailable lane, the "high" band, a worker lane resting on monitoring data, the empty state, light and dark, wide and narrow) SHALL be rendered in a real browser by the test suite, and its screenshot SHALL be compared with the approved reference.

#### Scenario: Layout change
- **WHEN** a change moves or overlaps nodes or bands
- **THEN** the screenshot comparison fails

### Requirement: Explore by hover, focus and click
Hovering or focusing a node or band SHALL highlight its lane and dim the others. Choosing a node (click, Enter or Space) SHALL open a detail panel listing its fields with units, sources, assumptions and warnings as the API sent them. Choosing it again, or pressing Escape, SHALL close the panel. The panel SHALL NOT state anything the data does not show and SHALL NOT name a facility.

#### Scenario: Highlight
- **WHEN** a node is hovered or focused
- **THEN** its lane stays prominent and the other lane is dimmed

#### Scenario: Detail
- **WHEN** the community receptor node is chosen
- **THEN** the panel lists the age band, its share of residents, its dose, and the total residents and radius

#### Scenario: Escape
- **WHEN** the panel is open and Escape is pressed
- **THEN** it closes and a fullscreen panel is not left

#### Scenario: Both ventilation tiers
- **WHEN** the worker endpoint is chosen
- **THEN** the panel lists the worst-case ventilation values the API sent, and no baseline values (the chain carries the worst case only)

### Requirement: Accessible and responsive
Every node SHALL be a keyboard-focusable control whose accessible name states its step, label and value. Bands SHALL be described in text for screen readers (for example "release to outdoor air: 1 g/s"). Flow animation SHALL be off when the user prefers reduced motion.

#### Scenario: Keyboard
- **WHEN** the user tabs through the diagram
- **THEN** each node takes focus in lane order and Enter opens its detail

#### Scenario: Narrow panel
- **WHEN** the panel is narrower than the diagram's minimum width
- **THEN** the diagram keeps its legible size and scrolls horizontally

#### Scenario: Reduced motion
- **WHEN** the user prefers reduced motion
- **THEN** the flow animation is not played

## REMOVED Requirements

### Requirement: Follows the facility the user is looking at
**Reason**: The tab no longer shows one facility. It draws the run's worst-case chain, which names no facility, so the map pin, the chat selection and the picker no longer drive it.
**Migration**: To look at one facility, use the facility inspector on the map (its scenario and per-facility values are unchanged). The tab reads `worst_case_chain` instead of the focused facility's `exposure_graph`.
