# facility-assessment-tool Specification

## Purpose
TBD - created by archiving change batch-facility-assessment. Update Purpose after archive.

## Requirements

### Requirement: Tiered screening of every facility
By default the tool SHALL screen every facility of the chemical's inventory (for the place given), not only the largest emitters, in three tiers:
1. **Bound:** each facility's worst-case hazard quotient and cancer risk with the EPA global default stack, over the SCREEN3 weather combinations and the configured screening ambient temperatures, scaled by its emission rate; computed once per call per unit emission rate, with no request per facility.
2. **Own stacks, worst case:** every facility whose bound reaches the configured HQ threshold or the configured cancer-risk threshold gets its stacks (in evidence order, the global default stack last, so every one has stacks) and its worst case over the same weather combinations and temperatures, with no cap on how many (a configured safety bound, far above any chemical's inventory, may stop it, and then the facilities beyond it SHALL be listed as not assessed with that reason and a warning, never silently).
3. **Full:** the facilities whose own-stack worst case still reaches a threshold, highest worst-case risk first (HQ, then cancer risk), up to `max_facilities`, also get the weather at the site, the residents and the representative case.
A facility below both thresholds at tier 1 or tier 2 SHALL be screened out with its bound and the reason. Facilities screened in but beyond the full-assessment cap SHALL keep their own-stack worst case, labelled as worst case only. When the chemical has neither an RfC nor an IUR, nothing can be screened out: the facilities go to tier 2 and tier 3 by emission rate and the result says why. When FRS IDs are given, those facilities SHALL be assessed without screening, the first `max_facilities` in the order given with the full chain and the rest at their own-stack worst case, labelled worst case only; facilities asked for but not in the inventory SHALL be listed as not assessed. A facility SHALL be left not assessed only for a stated reason (no fallback exists, it is not in the inventory, or the safety bound was reached), and every such facility in the inventory SHALL be returned to the program with that reason. An invalid CAS number SHALL assess nothing and say why.

#### Scenario: A small emitter is screened out with its bound
- **WHEN** a facility's bound HQ is below the HQ threshold and it has no cancer bound at or above the risk threshold
- **THEN** it is screened out at tier 1 with its bound, and no request is made for it

#### Scenario: Ranked by risk, not by emissions
- **WHEN** a facility with a lower emission rate has a higher own-stack worst-case HQ than a larger emitter
- **THEN** it is fully assessed before the larger emitter

#### Scenario: Refined below the threshold
- **WHEN** a facility's bound reaches the threshold but its own-stack worst case does not
- **THEN** it is screened out at tier 2 with its own-stack worst case

#### Scenario: Beyond the full-assessment cap
- **WHEN** more facilities stay above a threshold than `max_facilities`
- **THEN** the rest keep their own-stack worst case, labelled worst case only, and the result counts them

#### Scenario: No benchmark
- **WHEN** the chemical has neither an RfC nor an IUR
- **THEN** no facility is screened out and the result says screening was not possible

#### Scenario: Facilities by ID
- **WHEN** FRS IDs are given, one of them not in the inventory
- **THEN** the others are fully assessed in the order given and the missing one is listed with the reason

#### Scenario: Every candidate is refined
- **WHEN** 700 facilities have a bound at or above a threshold
- **THEN** all 700 get their stacks (the global default when nothing better exists) and their own-stack worst case, and none is listed as not assessed for a limit on how many are refined

#### Scenario: Safety bound reached
- **WHEN** more facilities reach a threshold than the configured safety bound
- **THEN** those beyond it are returned as not assessed with the reason "more than N facilities reach a threshold", and a warning says so

#### Scenario: Facilities by ID beyond the full-chain cap
- **WHEN** 30 FRS IDs of inventory facilities are given and `max_facilities` is 25
- **THEN** the first 25 are fully assessed and the other 5 keep their own-stack worst case, labelled worst case only, and none is listed as not assessed

### Requirement: Stacks in evidence order, never missing
For each facility the tool SHALL use its NEI stack candidates when it has EIS IDs with NEI rows; otherwise the PSTK stacks of the SCC processes that match its industry title with a similarity at or above a configured floor, distinct values only, at most a configured number, evaluated as a range; otherwise the EPA global default stack. The industry title SHALL come from the inventory record, else from the facility's TRI submission. Each facility SHALL carry its stack tier and notes saying why a better source could not be used.

#### Scenario: Own stacks
- **WHEN** the facility has EIS IDs with NEI rows
- **THEN** its NEI candidates are evaluated and no SCC search is made

#### Scenario: Process-typical stacks
- **WHEN** the facility has no EIS registration and its industry matches SCCs above the floor with PSTK rows
- **THEN** up to the configured number of distinct PSTK stacks are evaluated, the SCCs are named and the note says why NEI was not used

#### Scenario: Generic stack
- **WHEN** no SCC matches closely enough, none has a PSTK row, or the industry is unknown
- **THEN** the global default stack is evaluated and the notes say why and that it is generic

### Requirement: Benchmarks given or looked up
The tool SHALL use the RfC and IUR passed to it (for example a read-across surrogate's) and otherwise the chemical's own from CompTox, reporting which, with a warning when a benchmark is missing.

#### Scenario: Surrogate values
- **WHEN** toxicity values are passed
- **THEN** they are used and CompTox is not asked

### Requirement: Concurrent, in the run's context
Facilities SHALL be refined (tier 2) and assessed (tier 3) a configured number at a time, each in a copy of the caller's context so the run's service keys reach every request, with the results in the order selected. The SCC search SHALL be serialized and made once per industry title in a call. A facility's tier-2 stacks SHALL be reused at tier 3. Facilities in the same reanalysis grid cell (the configured cell size) and year SHALL share one weather request in a call. An error that is not a data or network problem SHALL be raised.

#### Scenario: One weather request per grid cell
- **WHEN** two fully assessed facilities lie in the same grid cell and year
- **THEN** the weather is requested once

#### Scenario: Keys reach every facility
- **WHEN** the run holds a service key in a context variable
- **THEN** every facility's steps see it

### Requirement: Two views
The model SHALL receive a compact summary: the benchmarks used and their source, the screening thresholds, how many facilities were found, screened out at each tier (with the highest bound screened out), assessed in full and kept at worst case only, the count per stack tier, and per fully assessed facility its identity, emission rate, stack tier and count, SCCs, industry, weather source, residents and radius, the worst-case and representative ranges of concentration, HQ and cancer risk, and at most a configured number of deduplicated notes, highest worst-case HQ first; per worst-case-only facility (at most a configured number, the rest counted) its identity, emission rate, stack tier and worst-case HQ and cancer risk; plus the facilities not assessed. The program SHALL receive every assessed facility's complete chain, every screened-out facility's record and bound, and every not-assessed facility with its reason, as the artifact.

#### Scenario: Summary only to the model
- **WHEN** the tool returns
- **THEN** the model's text has no stack lists and no screened-out facility list, and the artifact has every assessed facility's stacks and exposure (with weather and residents when fully assessed) and every screened-out facility's bound

#### Scenario: Not assessed travel to the program
- **WHEN** a facility of the inventory is left not assessed
- **THEN** the artifact lists it with its FRS ID and reason, though the model's text only counts and lists them as before

### Requirement: Description guides the use
The description SHALL say what the tool does (it screens every facility of the inventory, and what each tier means), what it needs and what it returns, to report every fully assessed facility and the worst-case-only ones rather than a sample, and the screening counts and thresholds, to give FRS IDs only when the user asks about particular facilities, what each stack tier means (and that the generic default must be stated), that the CAS number is never recalled from a name, and that results are screening estimates.

#### Scenario: Description content
- **WHEN** the description is read
- **THEN** it contains each of the points above

### Requirement: Category facilities when TRI has no release of the chemical
When the CAS number has no TRI release of its own but is a member of one or more TRI categories,
the batch assessment SHALL take its facilities from those categories, asking the emissions
inventory for each category code with the same state and city filter. Facilities SHALL be one
per facility and medium; a facility reported under several categories SHALL keep its larger
release. The result SHALL say, in its warnings, that the chemical has no release of its own,
which categories its facilities are from, and that their releases cover every member of each
category together. The benchmarks SHALL remain the chemical's own. When the chemical has its own
TRI releases, those SHALL be used and the categories SHALL NOT be queried.

#### Scenario: Member with no own releases
- **WHEN** the CAS number is a member of category N084 and TRI has no release of it
- **THEN** the facilities are those reported under N084, and a warning names the category and says its releases cover every member

#### Scenario: Own releases win
- **WHEN** TRI has releases of the CAS number itself
- **THEN** only those are assessed and no category is queried

#### Scenario: Facility in two categories
- **WHEN** a facility reports under two categories of the chemical
- **THEN** it is assessed once, with the larger release, and a warning says so

#### Scenario: Benchmarks stay the chemical's own
- **WHEN** the chemical's facilities come from a category
- **THEN** the toxicity values are looked up for the chemical's CAS number

### Requirement: Analogue benchmarks are disclosed and gated
When the chemical has no inhalation benchmark of its own and none is given, the batch
assessment SHALL run the read-across tool. It SHALL use the nearest TRI analogue's benchmarks only
when that match is within the applicability domain, and SHALL then name the analogue, its name,
its hybrid score and the applicability-domain threshold in `toxicity_source`, and say in the
warnings that the values are a read-across estimate, not measured values for the chemical, and
that the molecular-weight scaling factor was not applied. An out-of-domain analogue SHALL NOT be
used; the warnings SHALL give its score and the threshold.

#### Scenario: In-domain analogue
- **WHEN** the chemical has no benchmark and its analogue scores at or above the threshold with a benchmark
- **THEN** the analogue's benchmark is used and `toxicity_source` names the analogue, its score and the threshold

#### Scenario: Out-of-domain analogue
- **WHEN** the analogue scores below the threshold
- **THEN** no benchmark is used and the warnings give the score and the threshold

#### Scenario: Own benchmark
- **WHEN** CompTox gives the chemical's own benchmark
- **THEN** no analogue is consulted

### Requirement: A failed TRI read is never a fallback trigger or an absence
When TRI cannot be read for the chemical or for a category, the batch assessment SHALL NOT use
the category route and SHALL NOT report that the chemical has no releases. It SHALL assess no
facility and report that the assessment was not completed because TRI could not be read, so the
user can retry. The emissions inventory tool SHALL report the same failure in its note, not an
empty list alone.

#### Scenario: Own read fails
- **WHEN** the TRI request for the chemical fails after its retries
- **THEN** no category is queried, no facility is assessed, and the warnings say the assessment was not completed

#### Scenario: Category read fails
- **WHEN** the TRI request for a category fails
- **THEN** the assessment is not completed and no partial set of facilities is assessed

#### Scenario: Emissions tool
- **WHEN** the emissions inventory tool cannot read TRI
- **THEN** the note says TRI could not be read and that this is not evidence of no releases

### Requirement: Community, occupational and profile results per facility
The system SHALL return for every fully assessed or worst-case-only facility its community result (the existing ambient result `exposure`, unchanged in name and value), its `occupational_exposure` and its `operational_profile`. Screening-out and tier selection SHALL remain driven by the community bound only: a facility is not screened out or kept because of its occupational result, and the occupational result SHALL be computed for every facility the assessment evaluates, including those kept at worst case only. The occupational fields SHALL appear in the program's complete result; the text the model reads SHALL carry each facility's tier and ratio in one line.

#### Scenario: Chemical looked up once
- **WHEN** the assessment is run
- **THEN** the limits and vapor pressure come from one lookup of the chemical, made with the values the user entered in the thread, also when the benchmarks were given

#### Scenario: Lookup cannot be made
- **WHEN** benchmarks are given and the lookup cannot be made
- **THEN** the assessment goes on, the worker result has no limit and the warnings say why

#### Scenario: Three results
- **WHEN** a facility is assessed
- **THEN** it carries community, occupational and profile results

#### Scenario: Screening unchanged
- **WHEN** a facility's community bound would screen it out
- **THEN** it is still screened out and the occupational result is not computed for it

#### Scenario: Worst-case-only facility
- **WHEN** a facility is kept at worst case only
- **THEN** its occupational result is still computed and its community result is the worst case

#### Scenario: One request
- **WHEN** many facilities are assessed
- **THEN** no request per facility is made for the occupational result beyond the single PubChem record of the chemical

### Requirement: Worst-case scenarios per assessed facility
The assessment SHALL return for every fully assessed facility its worst-case scenarios (one per registered pathway and quantity that has a value, today the community hazard quotient and cancer risk and the worker results) with the receptors of each, as defined by the worst-case scenario capability, and SHALL identify the driving facility of each. A scenario SHALL be built from the values the assessment already holds (the per-stack results, the facility's population tracts and the worker result) and SHALL NOT trigger another request. A worst-case-only facility SHALL carry the scenario its worst case supports, without receptors. The text the model reads SHALL name the driving facility and stack of each result in one line and SHALL NOT list the receptors.

#### Scenario: Full facility
- **WHEN** a facility is fully assessed
- **THEN** it carries its scenarios, each with the stack, conditions and ranked receptors

#### Scenario: Worst case only
- **WHEN** a facility is kept at worst case only
- **THEN** its scenario has the stack and conditions of the worst case and says receptors were not evaluated

#### Scenario: No extra requests
- **WHEN** the scenarios are built
- **THEN** no population or exposure request is made beyond the ones the assessment makes

#### Scenario: Driver in the text
- **WHEN** several facilities are assessed
- **THEN** the text the model reads names which facility and stack drive each result

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
