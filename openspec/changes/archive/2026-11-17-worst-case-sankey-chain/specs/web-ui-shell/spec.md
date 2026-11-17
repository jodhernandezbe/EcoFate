## MODIFIED Requirements

### Requirement: Overview has an Exposure chain tab
The Overview SHALL offer a third tab, "Exposure chain", beside Summary and Risk by group, showing the
run's worst-case chain (one lane per pathway, no facility named). Risk by group SHALL be unchanged; the
Summary SHALL no longer hold the worst-case scenarios card, whose content the chain now carries. The
diagram SHALL keep its selection while the user switches tabs.

#### Scenario: Third tab
- **WHEN** the user opens the Overview
- **THEN** the switch offers Summary, Risk by group and Exposure chain

#### Scenario: State kept
- **WHEN** the user opens a node's detail, switches to Summary and back
- **THEN** the same node's detail is still open

### Requirement: Empty sections take their content height
A section of the executive summary that has no data SHALL occupy only the height of its content;
grid rows SHALL grow to share the panel only when they hold data. At first load the summary
cards SHALL be visible without scrolling at the default panel size.

#### Scenario: First load
- **WHEN** the workspace has no facilities
- **THEN** the risk, worker, chemical, population and meteorology cards are visible without scrolling, with no worst-case section above them

#### Scenario: Scenarios present
- **WHEN** the workspace has scenario drivers
- **THEN** the summary shows no worst-case section; the worst cases are in the Exposure chain tab

## REMOVED Requirements

### Requirement: Pinning a facility focuses it
**Reason**: The Exposure chain tab no longer follows a facility; it draws the run's worst-case chain.
**Migration**: A click on a marker still pins it and opens the facility inspector on the map; nothing else listens to the pin.

### Requirement: The summary ribbon shows the driving scenario
**Reason**: The Exposure chain tab shows the worst case of each pathway, with its factors, its most affected residents and the reason when there are none, so the Summary card repeated it. The card also named facilities, which the Overview no longer does.
**Migration**: Use the Exposure chain tab (the chain's nodes and their detail panel). The per-facility scenarios are still in the facility inspector on the map and in the report.
