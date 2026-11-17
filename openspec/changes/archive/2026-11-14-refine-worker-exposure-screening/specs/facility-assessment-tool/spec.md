## ADDED Requirements

### Requirement: Worker-only facilities get a worker result and no community result
The assessment SHALL give every worker-only facility (fugitive air release, no stack release) its occupational result and operating profile, and SHALL NOT compute a community result for it: no stack, no dispersion, no screening bound, and no weather or population request. Its community values SHALL be absent with the reason that it reports no stack release, never zero and never a band. It SHALL NOT be counted among the facilities screened, refined, fully assessed or screened out on the community bound; the result SHALL count worker-only facilities separately. The text the model reads SHALL say how many there are and name the one with the highest worker value.

#### Scenario: Worker result only
- **WHEN** a facility reports only a fugitive air release
- **THEN** it has an occupational result, and its community values are absent with the reason

#### Scenario: Screening counts unchanged
- **WHEN** worker-only facilities are present
- **THEN** the counts of screened-out, refined and fully assessed facilities equal what they are without them, and a separate count gives the worker-only ones

#### Scenario: No extra requests
- **WHEN** a worker-only facility is assessed
- **THEN** no weather, population or stack lookup is made for it

### Requirement: Screened-out facilities keep their worker result
The assessment SHALL give every facility screened out on the community screen (at the bound or with its own stacks) its occupational result and operating profile, because the community screen does not bound what workers breathe. Its community stage, values, reason and the screening counts SHALL stay as they are without the worker result. The text the model reads SHALL give each listed screened-out facility's worker band, the number of screened-out facilities in each worker band (with "not computed" for those without a value), and the screened-out facility with the highest worker value, and its note SHALL say that the screened-out facilities' workers were still screened.

#### Scenario: Worker result after a community screen-out
- **WHEN** a facility is screened out at the bound or with its own stacks
- **THEN** its artifact entry has an occupational result and an operating profile, and its stage, values and reason are unchanged

#### Scenario: Band counts and the highest worker value
- **WHEN** facilities are screened out
- **THEN** the screening summary counts them by worker band and names the one with the highest worker value (band, then worst-case 8-hour average)

#### Scenario: Nothing screened out
- **WHEN** no facility is screened out
- **THEN** the band counts are empty and no highest worker value is given
