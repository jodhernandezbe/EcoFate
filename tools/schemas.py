"""Typed payloads shared by tool inputs and outputs."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class ChemicalProperties(TypedDict):
    """Physical-chemical and toxicity values for one chemical, in the units noted below.

    A value is None when it could not be obtained or converted; ``warnings`` says why.
    """

    preferred_name: str | None  # the name CompTox calls it by; None = refer to it by CAS only
    molecular_weight: float | None  # g/mol
    vapor_pressure: float | None  # mmHg, as reported by the source (typically 25 C)
    density: float | None  # g/cm^3
    rfd: float | None  # oral reference dose, mg/(kg*day)
    rfc: float | None  # inhalation reference concentration, mg/m^3
    sf: float | None  # oral cancer slope factor, (mg/(kg*day))^-1
    iur: float | None  # inhalation unit risk, (ug/m^3)^-1
    # field -> "CompTox", "experimental", "predicted", a ToxVal source, or "PubChem" (fallback)
    sources: dict[str, str]
    toxicity_details: dict[str, ToxicityDetail]  # rfd/rfc/sf/iur found -> route and endpoint
    warnings: list[str]  # one entry per missing or unconvertible value
    missing: list[MissingEntry]  # missing values the result needs and the user may still enter
    occupational_limits: OccupationalLimits  # PubChem OSHA/NIOSH/ACGIH/IDLH/PAC limits, mg/m^3


class LimitValue(TypedDict):
    """One occupational limit PubChem lists, in mg/m^3."""

    value: float  # mg/m^3
    programme: str  # e.g. "OSHA PEL-TWA"
    converted_from_ppm: bool  # True when the record gave ppm and it was converted with the weight
    statements: int  # how many clear statements it comes from (the median when more than one)


class OccupationalLimits(TypedDict):
    """Occupational exposure limits read from the chemical's PubChem record.

    ``oel_twa_mg_m3`` is the 8-hour TWA benchmark chosen in the order OSHA PEL, NIOSH REL, ACGIH
    TLV; it and ``oel_source`` are None when none is available. ``limits`` holds every limit
    found (TWA, STEL, IDLH, PAC-1/2/3) under its key; ``reasons`` says why each other one is
    missing. A limit is never guessed.
    """

    oel_twa_mg_m3: float | None  # mg/m^3, 8-hour time-weighted average benchmark
    oel_source: str | None  # e.g. "OSHA PEL-TWA (PubChem)"
    limits: dict[str, LimitValue]  # limit key -> value
    reasons: dict[str, str]  # limit key -> why there is none
    warnings: list[str]


class PropertyValue(TypedDict):
    """One physical-chemical property value looked up from CompTox."""

    value: float  # in `unit`, exactly as reported by the source
    unit: str  # source unit string, e.g. "mmHg"; never converted
    source: Literal["experimental", "predicted"]  # median type the value came from


class ToxicityValue(TypedDict):
    """One toxicity value (RfD, RfC, SF, IUR, ...) looked up from CompTox ToxVal."""

    value: float  # in `unit`, exactly as reported by the source
    unit: str  # source unit string, e.g. "mg/kg-day"; never converted
    source: str  # ToxVal source database name for the chosen record
    route: str  # exposure route as recorded on the chosen record, lower-case, e.g. "oral"
    endpoint: str | None  # critical effect or cancer endpoint, e.g. "leukemia"; None if unstated
    assessment: str | None  # "cancer" or "non-cancer" as recorded; None if unstated


class ToxicityDetail(TypedDict):
    """Context of one toxicity value, for explaining it to the user."""

    source: str  # database the value comes from, e.g. "IRIS"
    exposure_route: str  # route the value applies to: "oral" or "inhalation"
    route_reported: str  # route as recorded by the source; "not specified" if it gave none
    endpoint: str | None  # critical effect or cancer endpoint, e.g. "leukemia"; None if unstated
    assessment: str | None  # "cancer" or "non-cancer"; None if unstated


class ConditionOfUse(TypedDict):
    """One TSCA condition of use implied by an activity a facility reported to TRI."""

    tri_activity: str  # the TRI activity, e.g. "As a reactant"
    tri_section: str  # its Form R Section 3 item, e.g. "3.2a"
    lifecycle_stage: str  # TSCA life cycle stage, e.g. "Processing"
    cou_category: str  # TSCA condition-of-use category, e.g. "Processing as a reactant"
    mapping_strength: str  # how well the activity matches it, as the crosswalk states it


class CdrSector(TypedDict):
    """The TSCA Chemical Data Reporting industrial sector of a facility's NAICS code."""

    code: str  # CDR industrial sector code, e.g. "IS21"
    name: str  # the sector's name
    matched_naics_prefix: str  # the NAICS prefix of EPA's crosswalk that matched
    naics_edition: str  # NAICS edition of that prefix, e.g. "2007"


class OperationalProfile(TypedDict):
    """How a facility operates and where it sits in the TSCA framework (from public sources).

    A value is None when its source does not give it; ``warnings`` says why. Nothing is guessed.
    """

    naics_code: str | None  # primary NAICS code TRI reports (2-6 digits)
    life_cycle_stage: list[str]  # TSCA stages of the activities the facility reported to TRI
    cou_category: list[str]  # TSCA condition-of-use categories of those activities
    cdr_sector: CdrSector | None  # CDR industrial sector of the NAICS code
    days_per_week: int | None  # d/week, derived from the Census QPC hours per week
    operating_days_per_year: float | None  # d/yr
    hours_per_day: float | None  # h/day
    annual_operating_hours: float | None  # h/yr, at most 8,760
    schedule_source: str  # where the hours come from (Census QPC release and code, or default)
    warnings: list[str]


class EmissionRecord(TypedDict):
    """One facility's most recent reported release of a chemical to one environmental medium."""

    frs_id: str  # EPA Facility Registry Service identifier
    facility_name: str | None
    environmental_medium: str  # TRI medium, e.g. "AIR STACK"
    reporting_year: int  # latest year the facility reported for this medium
    doc_ctrl_num: (
        str | None
    )  # TRI control number of that year's submission (its highest, if several)
    naics_code: (
        str | None
    )  # primary NAICS code of that submission (2-6 digits); None if TRI has none
    naics_title: str | None  # that code's title in words (Census code lists); None if unknown
    naics_subsector: str | None  # first three digits of `naics_code`; None if it has fewer
    naics_subsector_title: str | None  # that subsector's title (Census); None if unknown
    eis_ids: list[str]  # the facility's NEI (EIS) facility IDs; empty when FRS has none
    eis_note: str | None  # why `eis_ids` is empty, or that they were borrowed from an FRS twin
    total_release: float  # annual quantity, in `unit`, exactly as reported
    unit: str  # unit of `total_release` as reported, e.g. "Pounds"
    emission_rate: float  # g/s, total_release averaged over `operating_hours_per_year`
    fugitive_release_kg_per_year: float | None  # TRI fugitive air release, kg/yr; None if none
    fugitive_reporting_year: int | None  # year of that fugitive release; None if none
    operating_hours_per_year: float  # h/yr assumed for `emission_rate`
    operating_hours_source: str  # where those hours came from (industry baseline or default)
    conditions_of_use: list[ConditionOfUse]  # TSCA conditions of use of the reported activities
    lifecycle_stages: list[str]  # the distinct TSCA life cycle stages of `conditions_of_use`
    conditions_note: str | None  # why `conditions_of_use` is empty; None when it is not
    latitude: float  # decimal degrees, positive north
    longitude: float  # decimal degrees, negative west of Greenwich
    address: str | None  # street address
    city: str | None
    county: str | None
    state: str | None  # postal abbreviation, e.g. "TX"
    zip_code: str | None


class InventoryResult(TypedDict):
    """What the model is told about an inventory: the largest facilities and how many there are.

    The complete list is not part of it; a widely reported chemical has over a thousand
    facilities, too many to read or rank, so only the largest are listed.
    """

    total_found: int  # facilities found for the chemical, before any filter
    matching: int  # facilities that match the filters given (all of them without filters)
    shown: int  # facilities listed below
    facilities: list[EmissionRecord]  # the largest ``emission_rate`` first
    note: str | None  # says when the list is partial and how to see others; None when complete


StackSource = Literal["NEI", "PSTK", "AirToxScreen global default"]


class StackParameters(TypedDict):
    """Release-point geometry and plume conditions.

    The four values are all set or all None (never mixed across sources); ``warnings`` says
    why they are missing or which rule chose them.
    """

    stack_height: float | None  # m above ground
    stack_diameter: float | None  # m
    exit_velocity: float | None  # m/s
    exit_temperature: float | None  # K
    source: StackSource | None  # where the values come from; None when there are none
    scc: str | None  # SCC whose PSTK row supplied the values; None otherwise
    warnings: list[str]


class SccMatch(TypedDict):
    """One SCC whose process description matches an industry description."""

    scc: str  # Source Classification Code, e.g. "30600101"
    level_one: str  # broadest category, e.g. "Industrial Processes"
    level_two: str
    level_three: str
    level_four: str  # most specific process description
    sector: str  # EPA emission sector, e.g. "Industrial Processes - Petroleum Refineries"
    score: float  # semantic similarity, 0 (unrelated) to 1 (identical)


class SccLookupResult(TypedDict):
    """Candidate SCCs for an industry description, best first."""

    matches: list[SccMatch]
    warnings: list[str]


class Meteorology(TypedDict):
    """Representative boundary-layer conditions at a point, for one year.

    The values are annual representatives (not worst-case conditions) from a gridded
    reanalysis; ``source`` says "screening default" when no data could be used.
    """

    wind_speed: float  # m/s, annual mean at 10 m (not below the configured minimum)
    wind_direction: float  # degrees clockwise from north, direction wind blows from
    stability_class: str  # Pasquill-Gifford class "A" (unstable) to "F" (stable)
    ambient_temperature: float  # K, annual mean
    source: str  # data source and year, or "screening default"
    warnings: list[str]  # hours excluded, adjustments made, or why the default was used


class TractReceptor(TypedDict):
    """The residents of one census tract and where its internal point lies from the facility."""

    geoid: str  # state + county + tract FIPS code, 11 digits
    residents: int  # persons, the tract's ACS estimate (not scaled to the circle)
    age_distribution: dict[str, float]  # age band "0-4", "5-17", "18-64", "65+" -> percent
    distance_m: float  # m, great circle from the facility to the tract's internal point
    bearing_deg: float  # degrees clockwise from north, from the facility to that point
    latitude: float  # decimal degrees, the tract's internal point as the census service gave it
    longitude: float  # decimal degrees
    land_area_km2: float  # km^2


class Population(TypedDict):
    """Residents living within a search radius, from census estimates or a labelled default.

    ``source`` is "screening default" when no census data could be used.
    """

    total_population: int  # residents within the radius
    age_distribution: dict[str, float]  # age band "0-4", "5-17", "18-64", "65+" -> percent
    source: str  # data source and vintage, or "screening default"
    warnings: list[str]  # tracts left out, or why the default was used
    tracts: NotRequired[list[TractReceptor]]  # nearest first; empty for the screening default
    tracts_not_listed: NotRequired[int]  # tracts with residents beyond the listing limit


class Toxicity(TypedDict):
    """Inhalation toxicity values used for risk characterization.

    A value is None when it could not be obtained; the matching risk result is then None.
    """

    rfc: float | None  # mg/m3, inhalation reference concentration
    iur: float | None  # (ug/m3)^-1, inhalation unit risk


class ScenarioResult(TypedDict):
    """The screening result for one set of weather conditions.

    Every number is None when it could not be computed; the result's warnings say why.
    """

    max_concentration: float | None  # ug/m3, annual-average ground-level maximum
    max_concentration_1h: float | None  # ug/m3, 1-hour maximum before the annual factor
    distance_m: float | None  # m, downwind distance of the maximum
    stability_class: str | None  # Pasquill-Gifford class at the maximum
    wind_speed: float | None  # m/s at 10 m, at the maximum
    effective_release_height: float | None  # m, stack height plus plume rise
    hq: float | None  # unitless hazard quotient (annual exposure concentration / RfC)
    cancer_risk: float | None  # unitless lifetime excess cancer risk (exposure concentration x IUR)


class ExposureMetrics(ScenarioResult):
    """Screening-level exposure results for one stack.

    The fields of ``ScenarioResult`` are the EPA SCREEN3-style worst case over a grid of
    weather and distances; ``representative`` is the same for the weather of the meteorology
    input. ``add`` is the highest dose among the age bands present.
    """

    stack_source: str | None  # where the stack came from: "NEI", "PSTK" or the EPA global default
    add: float | None  # mg/(kg*day), average daily dose of the most exposed age band
    add_band: str | None  # age band with the highest dose
    add_by_band: dict[str, float]  # age band present -> dose, mg/(kg*day)
    representative: ScenarioResult  # the result for the representative weather
    warnings: list[str]  # null results, defaults used and the method's limits


class StackExposure(ExposureMetrics):
    """The screening result for one of the stacks given, numbered from 1 in the order given.

    The four stack values are echoed so a result can be tied to its stack.
    """

    stack_number: int  # 1-based position of the stack in the list given
    stack_height: float | None  # m above ground
    stack_diameter: float | None  # m
    exit_velocity: float | None  # m/s
    exit_temperature: float | None  # K


class RangeEntry(TypedDict):
    """Lowest and highest value of one quantity over the stacks, and the stack behind each."""

    low: float
    high: float
    low_stack: int  # stack_number giving the lowest value
    high_stack: int  # stack_number giving the highest value


class RepresentativeRange(TypedDict):
    """Range over the stacks for the representative weather; None entries as in the worst case."""

    max_concentration: RangeEntry | None  # ug/m3, annual-average maximum, representative weather
    hq: RangeEntry | None
    cancer_risk: RangeEntry | None


class ExposureRange(TypedDict):
    """Range over the evaluated stacks; an entry is None when no stack has the quantity."""

    max_concentration: RangeEntry | None  # ug/m3, worst-case annual-average maximum
    hq: RangeEntry | None  # unitless hazard quotient, worst case
    cancer_risk: RangeEntry | None  # unitless lifetime excess cancer risk, worst case
    representative: RepresentativeRange  # the same three ranges for the representative weather


class FacilityExposure(TypedDict):
    """Screening results for every candidate stack of one facility, and their range."""

    results: list[StackExposure]  # one per stack given, in the order given
    range: ExposureRange | None  # None when no stack could be evaluated
    stacks_given: int
    stacks_evaluated: int  # stacks with a computed concentration
    warnings: list[str]  # facility-level notes (stacks not evaluated, no stack given)


class NeiStackResult(TypedDict):
    """Tier 1 stack candidates of a facility, from the NEI.

    ``candidates`` are distinct real stacks (never averaged), lowest stack first, each a
    ``StackParameters`` with source "NEI"; pass them all to one exposure calculation.
    """

    eis_ids: list[str]  # NEI facility IDs found for the FRS ID
    candidates: list[StackParameters]  # empty when the NEI has no usable stack
    total_candidates: int  # distinct combinations before the cap
    warnings: list[str]  # why candidates are missing, or what was merged or omitted


class FacilityIndustry(TypedDict):
    """The primary industry of one TRI submission (the one an emission record reports).

    The title (in words) is what the SCC process search needs; the code alone means nothing to
    it. Both are None when no industry could be determined; ``warnings`` says why.
    """

    naics_code: str | None  # six-digit NAICS code, digits only
    naics_title: str | None  # the title of the code, in words
    code_origin: str | None  # "reported" by the facility, "assigned" by EPA, or None if unknown
    source: str | None  # where the industry comes from; None when there is none
    warnings: list[str]  # why a value is missing, or that EPA assigned the code


class CategoryRef(TypedDict):
    """A TRI category a chemical is reported under."""

    code: str  # group code (N420) or, for a single-substance entry, its hyphenated CAS number
    name: str  # category name as TRI gives it


class ReadAcrossMatch(TypedDict):
    """The TRI chemical closest to a query chemical (itself, or a read-across surrogate).

    Every value that could not be obtained is None and ``warnings`` says why. Scores are
    dimensionless; the surrogate's toxicity values are never part of this result.
    """

    query_cas: str  # the CAS number as validated (hyphenated), or as given if invalid
    query_smiles: str | None  # canonical SMILES of the query chemical
    query_mw: float | None  # g/mol
    is_direct_tri_match: bool  # the query chemical is itself in the TRI catalog
    surrogate_tri_cas: str | None
    surrogate_name: str | None
    surrogate_smiles: str | None  # canonical SMILES
    surrogate_mw: float | None  # g/mol
    moldeberta_cosine_sim: float | None  # learned-embedding cosine, -1 to 1
    morgan_tanimoto_sim: float | None  # ECFP4 (radius 2) Tanimoto, 0 to 1
    hybrid_read_across_score: float | None  # alpha * cosine + (1 - alpha) * Tanimoto
    mw_scaling_factor: float | None  # query_mw / surrogate_mw; reported, never applied
    within_applicability_domain: bool  # hybrid score >= the configured threshold
    resolution_method: Literal[
        "direct_tri_catalog_match",
        "tri_category_member",
        "hybrid_read_across",
        "unresolved",
    ]
    query_categories: list[CategoryRef]  # TRI categories that list the query chemical (often none)
    surrogate_category: CategoryRef | None  # category TRI reports the surrogate under, if any
    warnings: list[str]  # why a value is None, filters not applied, or out of domain


AssessmentLevel = Literal["full", "worst case only"]
ScreeningStage = Literal["bound", "own stacks"]


class ScreeningBound(TypedDict):
    """A facility's conservative bound: the worst case with the EPA global default stack.

    The SCREEN3 worst-case weather and the most conservative screening ambient temperature,
    with a person at the maximum; None when the benchmark is missing.
    """

    hq: float | None  # unitless
    cancer_risk: float | None  # unitless lifetime excess risk


class VentilationTier(TypedDict):
    """The worker screening for one ventilation tier of the box model (None = not computable)."""

    label: str  # e.g. "Baseline manufacturing ventilation"
    ventilation_m3_per_s: float  # room ventilation rate Q, m^3/s
    mixing_factor: float  # k, unitless
    workplace_concentration_mg_m3: float | None  # mg/m^3 while the plant runs
    twa_mg_m3: float | None  # 8-hour time-weighted average, mg/m^3
    oel_ratio: float | None  # TWA over the occupational exposure limit; above 1 exceeds it
    hq: float | None  # worker hazard quotient (average daily concentration over the RfC)
    cancer_risk: float | None  # worker lifetime excess cancer risk
    risk_tier: str | None  # "exceedance", "elevated", "acceptable", or None


class OccupationalExposure(TypedDict):
    """Worker screening of one facility: EPA ChemSTEER box model and RAGS Part F dosimetry.

    The fugitive release is treated as generated only while the plant runs, in one well-mixed
    zone; the ventilation tiers are screening defaults, not the plant's; and it is not a
    compliance determination. A value is None when an input is missing; ``warnings`` says which.
    """

    fugitive_release_kg_per_year: float | None  # TRI fugitive air release, kg/yr
    fugitive_reporting_year: int | None  # year of that release
    operating_days_per_year: float | None  # d/yr
    hours_per_day: float | None  # h/day
    oel_twa_mg_m3: float | None  # 8-hour TWA limit used, mg/m^3
    oel_source: str | None  # e.g. "OSHA PEL-TWA (PubChem)"
    rfc: float | None  # mg/m^3, inhalation reference concentration used
    iur: float | None  # (ug/m^3)^-1, inhalation unit risk used
    vapor_pressure_mmhg: float | None  # context only; never enters an equation
    vapor_pressure_source: str | None  # "CompTox" (experimental/predicted) or "PubChem"
    baseline: VentilationTier
    worst_case: VentilationTier
    risk_tier: str | None  # the baseline tier; the worst case is in `worst_case`
    assumptions: list[str]
    warnings: list[str]


class ScenarioFactor(TypedDict):
    """One factor of a worst-case scenario: a value a tool returned, or why there is none."""

    key: str  # e.g. "stack_height"
    group: Literal["source", "release", "conditions", "receptor_model"]
    label: str
    value: float | str | None  # None when no tool reported it
    unit: str  # empty when unitless or when the value is text
    source: str | None  # where the value came from, when a tool said
    reason: str | None  # why there is no value


class ScenarioReceptor(TypedDict):
    """A receptor of a scenario: a census tract, or the workers of the facility."""

    kind: Literal["tract", "workers"]
    label: str  # the tract's geoid, or "Workers"
    residents: int | None  # persons (tracts)
    age_distribution: dict[str, float]  # age band -> percent (tracts); empty for workers
    distance_m: float | None  # m from the facility to the tract's internal point
    bearing_deg: float | None  # degrees clockwise from north
    latitude: float | None  # the tract's internal point, decimal degrees; None for workers
    longitude: float | None
    concentration: float | None  # ug/m^3, annual average the scenario gives at the receptor
    fraction_of_maximum: float | None  # that concentration over the scenario's maximum
    note: str | None


class WorstCaseScenario(TypedDict):
    """The combination of factors behind the high-end value of one quantity on one pathway.

    Every value is one a tool returned. ``tier`` is the level the assessment gave the value;
    it is a screening result, never a regulatory finding.
    """

    pathway_key: str  # e.g. "community_inhalation"
    pathway: str  # medium, route and receptor class
    quantity: str  # "hq", "cancer_risk" or "oel_ratio"
    quantity_label: str
    value: float  # unitless
    tier: str | None  # e.g. "above threshold", "exceedance"; None when none was given
    benchmark: float | None  # the level of concern the value was compared with, unitless
    factors: list[ScenarioFactor]
    receptors: list[ScenarioReceptor]
    receptors_note: str | None  # why there are none, or what was left out
    notes: list[str]


class ScenarioDriver(TypedDict):
    """The assessed facility whose scenario has the highest value of a pathway's quantity."""

    pathway_key: str
    quantity: str
    frs_id: str
    facility_name: str | None
    stack_number: int | None  # the stack behind the value (community pathways); else None
    value: float  # unitless


class FacilityAssessment(TypedDict):
    """The chain for one facility, as the batch assessment ran it (for the program).

    ``level`` is "full" (site weather, residents, worst and representative cases) or
    "worst case only" (its own stacks over the worst-case weather; no weather or residents).
    """

    record: EmissionRecord  # the inventory record assessed
    level: AssessmentLevel
    bound: ScreeningBound | None  # None when not screened (asked for by ID, or no benchmark)
    stacks: list[StackParameters]  # the stacks evaluated, all from one source
    stack_tier: StackSource  # where they come from: NEI, PSTK by SCC, or the global default
    scc_matches: list[SccMatch]  # the SCC matches whose PSTK stacks were used (PSTK tier only)
    industry: FacilityIndustry | None  # TRI's industry, when it had to be looked up
    meteorology: Meteorology | None  # None at worst case only
    population: Population | None  # None at worst case only
    radius_km: float | None  # radius the residents were counted in; None = the default
    exposure: FacilityExposure  # the community (ambient fenceline) result
    occupational_exposure: OccupationalExposure  # the worker screening
    operational_profile: OperationalProfile  # schedule, life cycle stage, COU, CDR sector
    notes: list[str]  # why a better stack source could not be used, and other choices made
    scenarios: NotRequired[list[WorstCaseScenario]]  # one per pathway and quantity with a value


class ScreenedOut(TypedDict):
    """A facility left out because its screening value is below both thresholds."""

    record: EmissionRecord
    stage: ScreeningStage  # "bound" (generic stack) or "own stacks" (its own worst case)
    hq: float | None  # the screening value compared with the threshold, unitless
    cancer_risk: float | None
    stacks: list[StackParameters]  # its own stacks ("own stacks" stage); empty at the bound
    stack_tier: StackSource
    reason: str


class AssessmentArtifact(TypedDict):
    """What the program receives from a batch assessment."""

    assessed: list[FacilityAssessment]  # fully assessed first, then worst case only
    screened_out: list[ScreenedOut]
    not_assessed: list[NotAssessed]  # asked for or reaching a threshold, but with no result
    drivers: NotRequired[list[ScenarioDriver]]  # the facility behind each scenario's top value


class NotAssessed(TypedDict):
    """A facility that was asked for but not assessed, and why."""

    frs_id: str
    reason: str


class FacilityRanges(TypedDict):
    """Ranges over a facility's stacks, worst case and representative weather; None = none."""

    concentration_worst: RangeEntry | None  # ug/m3, annual average, worst case over stacks
    concentration_representative: RangeEntry | None  # ug/m3, representative weather
    hq_worst: RangeEntry | None  # unitless
    hq_representative: RangeEntry | None
    cancer_risk_worst: RangeEntry | None  # unitless lifetime excess risk
    cancer_risk_representative: RangeEntry | None


class FacilitySummary(FacilityRanges):
    """One assessed facility as the model reads it: provenance, risk ranges and notes."""

    frs_id: str
    facility_name: str | None
    city: str | None
    state: str | None
    emission_rate: float  # g/s
    stack_tier: StackSource
    stacks_evaluated: int
    sccs: list[str]  # SCCs whose PSTK stacks were used (PSTK tier only)
    industry: str | None  # NAICS title, when known
    weather_source: str
    residents: int  # within the radius
    radius_km: float | None  # None = the default radius
    worker_risk_tier: (
        str | None
    )  # worker screening tier (baseline ventilation), None = not computed
    worker_oel_ratio: float | None  # worker 8-hour TWA over the occupational limit, unitless
    notes: list[str]  # the most important warnings, deduplicated and capped


class WorstCaseSummary(TypedDict):
    """A facility kept at its own-stack worst case only (beyond the full-assessment cap)."""

    frs_id: str
    facility_name: str | None
    city: str | None
    state: str | None
    emission_rate: float  # g/s
    stack_tier: StackSource
    hq_worst: RangeEntry | None  # unitless, over its stacks
    cancer_risk_worst: RangeEntry | None


class ScreenedOutSummary(TypedDict):
    """A screened-out facility as the model reads it: its screening value and emission rate."""

    frs_id: str
    facility_name: str | None
    city: str | None
    state: str | None
    emission_rate: float  # g/s
    stage: ScreeningStage
    hq: float | None
    cancer_risk: float | None


class ScreeningSummary(TypedDict):
    """How the facilities were screened: thresholds, counts and the closest call left out."""

    possible: bool  # False when the chemical has neither an RfC nor an IUR
    hq_threshold: float
    cancer_risk_threshold: float
    screened_out_at_bound: int
    screened_out_with_own_stacks: int
    closest_screened_out: list[ScreenedOutSummary]  # closest to a threshold first, capped


class AssessmentResult(TypedDict):
    """What the model is told about a batch assessment."""

    cas_number: str | None
    toxicity: Toxicity  # the benchmarks used
    toxicity_source: str  # "given" (passed in) or "CompTox"
    facilities_found: int  # in the inventory (for the place asked about)
    screening: ScreeningSummary | None  # None when facilities were asked for by ID
    assessed: int  # fully assessed
    stack_tiers: dict[str, int]  # tier -> number of facilities fully assessed with it
    facilities: list[FacilitySummary]  # fully assessed, highest worst-case HQ first
    worst_case_only_count: int
    worst_case_only: list[WorstCaseSummary]  # highest worst-case risk first, capped
    not_assessed: list[NotAssessed]
    note: str | None  # what was left out of the listing
    warnings: list[str]
    drivers: NotRequired[list[ScenarioDriver]]  # the facility behind each pathway's top value


class TriCategoryResult(TypedDict):
    """Which TRI categories list a CAS number (membership only; nothing is estimated)."""

    query_cas: str  # the CAS number as given, whitespace stripped
    categories: list[CategoryRef]  # every category that lists it; empty if none does
    warnings: list[str]  # e.g. the CAS number is not valid


class MissingEntry(TypedDict):
    """One value the assessment needs and could not find, to ask the user for."""

    entry_id: str  # unique within the request, e.g. "rfc:1330-20-7" or "stack_height:FAC1-S1"
    quantity: str  # a key of the user-value settings, e.g. "rfc" or "stack_height"
    subject: str  # the chemical's CAS number or the facility's stack the value belongs to
    accepted_units: list[str]  # units the entry takes; the first is the target unit
    minimum: float  # plausible range in the target unit, inclusive
    maximum: float
    purpose: str  # what the requested result uses the value for, in words


class ConfirmationRequest(TypedDict):
    """The values the assessment is waiting on, shown to the user as one request."""

    request_id: str
    entries: list[MissingEntry]
