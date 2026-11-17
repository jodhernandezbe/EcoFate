## MODIFIED Requirements

### Requirement: Interactive facility map
The analysis area SHALL show a vector basemap (light and dark styles from configuration) as soon
as the page loads, framed on the configured initial view (the contiguous United States), even
when no facility has been placed. It SHALL draw one marker per placed facility, sized by its total annual air release (kg/yr, as the
API sent it) on a square-root scale between the configured smallest and largest sizes, with the smallest
size when the total is absent. The marker SHALL be coloured by the screening band of the pathway chosen
in the map's pathway dropdown, or drawn as "No result on this pathway" when the facility has none. The
dropdown SHALL offer the same pathways, with the same labels, as Risk by group ("Outdoor Air → Inhalation
→ General Population", the default, and "Indoor Air → Inhalation → Worker"). The legend's entries ("High",
"Moderate", "Low", "No result on this pathway") SHALL each show how many facilities have that band on the
chosen pathway, and SHALL hide or show those markers, with their circles, sectors and cards, when pressed.
The legend SHALL say that size is the total annual air release, and SHALL say how many facilities have
none reported. Markers SHALL carry no ring for any other pathway. When the framing version changes, the camera SHALL animate to fit the bounding
box, with padding that keeps the framed facilities clear of the legend. The map SHALL redraw at
its new size whenever its container changes size (splitter drag, rail or chat collapse, panel
fullscreen, window resize), leaving no blank or stretched area. A "Reset to USA view" control
on the map SHALL return the camera to the configured initial view. It SHALL animate, or jump
when the user prefers reduced motion. For a facility with receptors the map SHALL draw the
receptor radius circle. With meteorology it SHALL draw a sector toward
`(wind_direction + 180) % 360` with a configured half-angle and the radius as length, labelled
"schematic downwind sector, not a modelled plume footprint".

#### Scenario: Before any query
- **WHEN** the page has loaded and no assessment has run
- **THEN** the basemap is visible, framed on the contiguous United States, with no markers

#### Scenario: Hide and show a status
- **WHEN** the user presses the "High" legend entry and later presses it again
- **THEN** the markers of facilities in the high band leave the map, with their circles, sectors and cards, and the entry reads as off with its count unchanged; pressing it again brings them back

#### Scenario: Legend counts
- **WHEN** on the outdoor pathway the workspace holds one low facility, two high and one with no community result
- **THEN** the legend entries show High 2, Moderate 0, Low 1 and No result on this pathway 1

#### Scenario: Fit to facilities
- **WHEN** a dashboard event raises the framing version
- **THEN** the camera flies to fit all placed facilities

#### Scenario: Container resized
- **WHEN** the user collapses the chat dock
- **THEN** the map fills the wider area without blank tiles or distortion

#### Scenario: Reset view
- **WHEN** facilities are framed and the user activates "Reset to USA view"
- **THEN** the camera returns to the contiguous United States and the markers stay placed

#### Scenario: Downwind sector
- **WHEN** the wind blows from 270°
- **THEN** the sector points toward 90°

#### Scenario: Worker pathway chosen
- **WHEN** a facility is "low" for the community and "high" for workers, and the user chooses the indoor pathway
- **THEN** its marker turns to the high look, the legend counts it under High, and no ring is drawn

#### Scenario: Size from the total release
- **WHEN** two facilities have totals of 100 and 400 kg/yr
- **THEN** the second marker is larger, on a square-root scale, whichever pathway is chosen

#### Scenario: Total not reported
- **WHEN** a facility's total annual air release is absent
- **THEN** its marker has the smallest size and the legend counts it as release not reported

### Requirement: The map marks the driving facility and its receptors
The map SHALL mark with an outer ring each facility that drives a worst-case result of the pathway chosen in the map's dropdown, and only those, and when that facility is selected SHALL draw its listed receptors at their bearing and distance, without drawing the receptors of other facilities. Receptors SHALL be drawn at the coordinates the tool returned, never at a position computed in the browser, only for the results the pinned facility drives, and a tract several results name SHALL be drawn once.

#### Scenario: Receptors drawn
- **WHEN** the driving facility is pinned
- **THEN** its listed receptors are drawn at the coordinates the tool gave

#### Scenario: Receptors removed
- **WHEN** the facility is unpinned or closed
- **THEN** no receptor is drawn

#### Scenario: Driver of the chosen pathway
- **WHEN** facility A drives the community hazard quotient, facility B drives the worker limit ratio, and the indoor pathway is chosen
- **THEN** only B carries the outer ring

### Requirement: Worker-only facilities are shown as such
A facility with a worker result and no stack release SHALL appear on the map sized by its total annual air release (its fugitive release) like any other facility. On the outdoor pathway it SHALL be drawn as "No result on this pathway" (outlined, no fill); on the indoor pathway it SHALL be filled by its worker band. No ring SHALL show its worker band. Its accessible name SHALL say it reports no stack release. Its inspector SHALL show the worker section and SHALL say the community result does not apply because the facility reports no stack release, never "not reported" alone and never zero. It SHALL be ranked on the indoor pathway of Risk by group and absent from the outdoor pathway.

#### Scenario: Marker
- **WHEN** a worker-only facility is on the map
- **THEN** on the outdoor pathway its marker is outlined with no fill and no worker ring, and on the indoor pathway it is filled by its worker band

#### Scenario: Inspector
- **WHEN** a worker-only facility is inspected
- **THEN** the community part says the facility reports no stack release and the worker section is shown

#### Scenario: Risk by group
- **WHEN** the outdoor pathway is chosen
- **THEN** worker-only facilities are not ranked, and on the indoor pathway they are

## REMOVED Requirements

### Requirement: Worker tier on the map
**Reason**: A ring for the worker band next to a fill for the community band made each marker encode two pathways at once, which was confusing.
**Migration**: Choose "Indoor Air → Inhalation → Worker" in the map's pathway dropdown, and the marker colour becomes the worker band. The facility inspector still shows both results.
