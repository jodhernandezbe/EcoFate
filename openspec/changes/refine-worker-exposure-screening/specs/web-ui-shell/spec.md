## MODIFIED Requirements

### Requirement: Worker card in the summary ribbon
The Overview summary ribbon SHALL include a "Worker exposure" card with the highest 8-hour TWA to limit ratio, worker hazard quotient and worker lifetime cancer risk over the assessed facilities, each for the baseline and the worst case, with the facility each comes from, its band in words and the evidence it rests on ("OSHA monitoring" or the driving activity), in the way the hazard quotient and cancer risk card names its facility. Where nothing is available it SHALL say why.

#### Scenario: Highest values
- **WHEN** several facilities have worker results
- **THEN** each figure is the highest among them and names its facility, its band and its evidence

#### Scenario: Nothing yet
- **WHEN** no facility has a worker result
- **THEN** the card shows "not reported" for each figure and the reason

### Requirement: Worker section in the facility inspector
The facility inspector (hover and pinned card) SHALL show a compact badge with the community band and hazard quotient and the worker band with its limit ratio, so a user can see whether the concern comes from the stack plume or from the workplace, and a "Worker exposure" section with the evidence the result rests on, the facility's operating schedule (days per year, hours per day, hours per year), life cycle stage and condition of use, CDR industrial sector, the chemical's vapor pressure against the range of the vapor models, the occupational limit and its source, the OSHA monitoring summary when there is one (industry level, samples, non-detects, years, median and 95th percentile), each evaluated activity with its estimator and its baseline and worst-case 8-hour averages with the driving one marked, for the baseline and the worst case the 8-hour TWA, limit ratio, worker hazard quotient and worker cancer risk and the band, the TRI fugitive release as context, and the warnings. The band SHALL be written as text as well as coloured.

#### Scenario: Both results
- **WHEN** a facility has a community and a worker result
- **THEN** the badge shows both bands and the section lists the baseline and the worst case

#### Scenario: Monitoring evidence
- **WHEN** a facility's worker result rests on OSHA monitoring data
- **THEN** the section says so, shows the monitoring summary and still lists the modelled activities

#### Scenario: Tier not by colour alone
- **WHEN** a band is shown
- **THEN** it is written in words

### Requirement: Worker tier on the map
The map SHALL draw a ring around each facility marker coloured by the worker band (none while it is not computed), and SHALL fill the marker by the community band, keeping its size for the emission rate; both SHALL use the same three looks. The legend SHALL explain the fill and the ring with the words "High", "Moderate" and "Low" and count the facilities of each band, and the marker's accessible name SHALL include both bands.

#### Scenario: Ring and fill
- **WHEN** a facility is "high" in the community result and "moderate" for workers
- **THEN** its marker is filled with the high look and ringed with the moderate look

#### Scenario: No worker result
- **WHEN** no facility has a worker result
- **THEN** no ring is drawn and the legend has no ring entry

#### Scenario: Accessible name
- **WHEN** a marker has a worker band
- **THEN** its accessible name includes the community and the worker band in words

### Requirement: Risk by group has an exposure pathway dropdown
The Risk by group view SHALL have one dropdown, above its three sections, that chooses the exposure pathway as medium, route and receptor: "Outdoor Air → Inhalation → General Population" (the default, the community result) or "Indoor Air → Inhalation → Worker" (the worker result). The choice SHALL apply to the three sections and be kept while the user goes to the summary and back. On the indoor pathway the quantity switch SHALL offer the worker hazard quotient, the worker lifetime cancer risk and the 8-hour average over the occupational limit, each bar being the highest value among the group's assessed facilities at the baseline. On both pathways the dashed lines SHALL be the band boundaries of the shown quantity from the client settings, labelled "moderate" and "high"; the indoor tooltip SHALL give the facility, its 8-hour average and its evidence. A bar's tooltip SHALL name the facility and stack that drive it. A facility with no worker value SHALL not be ranked, and a chart with nothing to rank SHALL say why. Leaving the indoor pathway while the limit ratio is shown SHALL return to the hazard quotient.

#### Scenario: Default
- **WHEN** the Risk by group view opens
- **THEN** it has one pathway dropdown, on the outdoor air pathway, with the band boundaries of the hazard quotient drawn

#### Scenario: Indoor air
- **WHEN** the user chooses the indoor air pathway
- **THEN** all three sections rank the worker values, with the same band boundaries drawn

#### Scenario: Limit ratio only for workers
- **WHEN** the outdoor air pathway is chosen
- **THEN** the limit ratio is not offered

#### Scenario: Nothing to rank
- **WHEN** no facility has a worker value
- **THEN** the chart says why, with no zero bars

#### Scenario: Bar names its driver
- **WHEN** the user hovers a bar
- **THEN** the tooltip names the facility and the stack that give its value

## ADDED Requirements

### Requirement: Worker-only facilities are shown as such
A facility with a worker result and no stack release SHALL appear on the map with an outlined marker that has no community fill and the worker ring, a fixed marker size (it has no emission rate), and an accessible name saying it reports no stack release. The legend SHALL explain the outlined marker and count these facilities. Its inspector SHALL show the worker section and SHALL say the community result does not apply because the facility reports no stack release, never "not reported" alone and never zero. It SHALL be ranked on the indoor pathway of Risk by group and absent from the outdoor pathway.

#### Scenario: Marker
- **WHEN** a worker-only facility is on the map
- **THEN** its marker is outlined, has no community fill and carries the worker ring

#### Scenario: Inspector
- **WHEN** a worker-only facility is inspected
- **THEN** the community part says the facility reports no stack release and the worker section is shown

#### Scenario: Risk by group
- **WHEN** the outdoor pathway is chosen
- **THEN** worker-only facilities are not ranked, and on the indoor pathway they are

### Requirement: Risk by group ranks every worker result on the indoor pathway
On the indoor pathway, Risk by group SHALL rank every facility that has a worker result, whether it was fully assessed, kept at the worst case, screened out on the community screen or worker-only, and its "assessed" count SHALL count the facilities with a worker result. The outdoor pathway SHALL be unchanged: screened-out facilities are counted as such and are never a bar.

#### Scenario: Screened-out facility indoors
- **WHEN** a screened-out facility has a worker result and the indoor pathway is chosen
- **THEN** its worker values can be its group's bars and it is counted as assessed, not as screened out

#### Scenario: Screened-out facility outdoors
- **WHEN** the outdoor pathway is chosen
- **THEN** the screened-out facility is counted as screened out and is not a bar
