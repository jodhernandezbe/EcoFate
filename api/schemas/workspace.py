"""Workspace contract: everything the left pane shows, built only from tool results.

Every number here was reported by a tool (or is a maximum of such numbers); a quantity no tool
reported is ``None``. Units are in the field descriptions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from api.schemas.base import ContractModel
from api.schemas.exposure_graph import ExposureGraph, GraphStatus

Status = GraphStatus
Tier = Literal[1, 2, 3]
ProvenanceKind = Literal[
    "not_evaluated",
    "direct_tri_match",
    "tri_category_member",
    "read_across",
    "unresolved",
]
NOT_COMPUTED = "not yet computed"


class Dose(ContractModel):
    """Inhalation average daily dose, mg/(kg·day), of the worst case, by age band of the residents.

    ``highest_band`` is the band with the largest dose (``highest_mg_kg_day``); ``by_band`` has
    every band that has residents. Children get larger doses because they breathe more per kg.
    """

    highest_mg_kg_day: float | None = None
    highest_band: str | None = None
    by_band: dict[str, float] = Field(default_factory=dict[str, float])


class Scenario(ContractModel):
    """Screening result for one set of weather: concentration µg/m³, HQ and cancer risk unitless."""

    max_concentration_ug_m3: float | None = None
    distance_m: float | None = Field(default=None, description="Downwind distance of the maximum.")
    hq: float | None = None
    cancer_risk: float | None = None


class Stack(ContractModel):
    """One release point with its provenance tier and, when computed, its results.

    Attributes:
        stack_number: 1-based position in the exposure call that evaluated it, else None.
        tier: 1 Empirical NEI, 2 PSTK by SCC, 3 EPA global default; None without a source.
        tier_label: ``Tier 1: Empirical NEI`` and so on.
        scc: SCC behind a PSTK stack, when reported.
        scc_description: Most specific process description of that SCC, from an SCC lookup
            in the same thread; None when no lookup returned it.
        scc_score: Match score (0-1) of that lookup.
    """

    stack_number: int | None = None
    height_m: float | None = None
    diameter_m: float | None = None
    exit_velocity_m_s: float | None = None
    exit_temperature_k: float | None = None
    source: str | None = None
    tier: Tier | None = None
    tier_label: str | None = None
    scc: str | None = None
    scc_description: str | None = None
    scc_score: float | None = None
    worst_case: Scenario | None = None
    representative: Scenario | None = None
    dose: Dose | None = None
    warnings: list[str] = Field(default_factory=list[str])


class Extreme(ContractModel):
    """The lowest and highest value of one quantity over a facility's stacks."""

    low: float
    high: float
    low_stack: int
    high_stack: int


class ExposureRanges(ContractModel):
    """Ranges over the evaluated stacks of one facility; None when no stack has the quantity."""

    stacks_given: int
    stacks_evaluated: int
    hq_worst: Extreme | None = None
    cancer_risk_worst: Extreme | None = None
    concentration_worst: Extreme | None = None
    hq_representative: Extreme | None = None
    cancer_risk_representative: Extreme | None = None
    concentration_representative: Extreme | None = None
    dose: Dose | None = Field(
        default=None,
        description="Per age band, the highest worst-case dose over the stacks.",
    )
    warnings: list[str] = Field(default_factory=list[str])


class Industry(ContractModel):
    """Primary industry of the TRI submission; origin is reported, assigned or None."""

    naics_code: str | None = None
    naics_title: str | None = None
    code_origin: str | None = None
    source: str | None = None


class Receptors(ContractModel):
    """Residents within ``radius_km`` of a point; ``age_distribution`` is percent per band."""

    total_population: int
    radius_km: float
    age_distribution: dict[str, float]
    source: str
    screening_default: bool
    warnings: list[str] = Field(default_factory=list[str])


class Meteorology(ContractModel):
    """Annual representative conditions at a point: m/s, degrees clockwise from north, K."""

    wind_speed_m_s: float
    wind_from_deg: float = Field(description="Direction the wind blows from.")
    wind_toward_deg: float = Field(description="Downwind direction, ``(from + 180) % 360``.")
    ambient_temperature_k: float
    stability_class: str
    source: str
    screening_default: bool
    latitude: float = Field(description="Point the weather is for, decimal degrees.")
    longitude: float = Field(description="Point the weather is for, decimal degrees.")
    frs_id: str | None = Field(default=None, description="Facility at that point, if one is.")
    facility_name: str | None = None
    warnings: list[str] = Field(default_factory=list[str])


class Polygon(ContractModel):
    """A GeoJSON polygon: one closed ring of ``[longitude, latitude]`` positions (WGS84)."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


ScreeningOutcome = Literal[
    "full",
    "worst_case_only",
    "screened_out_at_bound",
    "screened_out_with_own_stacks",
    "not_assessed",
]


class Screening(ContractModel):
    """How the batch assessment screened a facility.

    Attributes:
        outcome: Fully assessed; kept at its own-stack worst case only (no weather, residents
            or representative case); or screened out on the conservative bound (a generic
            short, cold stack) or on its own-stack worst case, below both thresholds; or not
            assessed, with the reason in ``reason``.
        bound_hq: The bound's hazard quotient (unitless), when computed.
        bound_cancer_risk: The bound's lifetime excess cancer risk (unitless), when computed.
        value_hq: The screening value compared with the threshold (the bound, or the own-stack
            worst case), unitless.
        value_cancer_risk: Likewise for the cancer risk.
        reason: Why the facility was screened out or not assessed, in words; None otherwise.
    """

    outcome: ScreeningOutcome
    bound_hq: float | None = None
    bound_cancer_risk: float | None = None
    value_hq: float | None = None
    value_cancer_risk: float | None = None
    reason: str | None = None


class ConditionOfUse(ContractModel):
    """One TSCA condition of use implied by a TRI activity the facility reported."""

    tri_activity: str
    tri_section: str
    lifecycle_stage: str
    cou_category: str
    mapping_strength: str


OccupationalTier = Literal["exceedance", "elevated", "acceptable"]


class VentilationTier(ContractModel):
    """The worker screening for one ventilation tier of the box model; None = not computed.

    Attributes:
        ventilation_m3_per_s: Room ventilation rate, m³/s.
        mixing_factor: Mixing factor k, unitless.
        workplace_concentration_mg_m3: Concentration while the plant runs, mg/m³.
        twa_mg_m3: 8-hour time-weighted average, mg/m³.
        oel_ratio: The average over the occupational limit (unitless); above 1 exceeds it.
        hq: Worker hazard quotient (unitless).
        cancer_risk: Worker lifetime excess cancer risk (unitless).
        risk_tier: "exceedance", "elevated" or "acceptable"; None when nothing could be compared.
    """

    label: str
    ventilation_m3_per_s: float
    mixing_factor: float
    workplace_concentration_mg_m3: float | None = None
    twa_mg_m3: float | None = None
    oel_ratio: float | None = None
    hq: float | None = None
    cancer_risk: float | None = None
    risk_tier: OccupationalTier | None = None


class OccupationalExposure(ContractModel):
    """Worker screening of a facility: EPA ChemSTEER box model and RAGS Part F dosimetry.

    A screening that assumes generic ventilation, not an OSHA compliance determination.

    Attributes:
        fugitive_release_kg_per_year: TRI fugitive air release, kg/yr (year in
            ``fugitive_reporting_year``).
        operating_days_per_year: Days a year the plant runs, d/yr.
        hours_per_day: Hours a day it runs, h/day.
        oel_twa_mg_m3: The 8-hour occupational limit used, mg/m³, with ``oel_source``.
        rfc: Reference concentration used, mg/m³.
        iur: Inhalation unit risk used, (µg/m³)⁻¹.
        vapor_pressure_mmhg: Context only; never enters an equation. Its source is in
            ``vapor_pressure_source``.
        baseline: The baseline manufacturing ventilation tier.
        worst_case: The enclosed-zone tier.
        risk_tier: The baseline tier.
    """

    fugitive_release_kg_per_year: float | None = None
    fugitive_reporting_year: int | None = None
    operating_days_per_year: float | None = None
    hours_per_day: float | None = None
    oel_twa_mg_m3: float | None = None
    oel_source: str | None = None
    rfc: float | None = None
    iur: float | None = None
    vapor_pressure_mmhg: float | None = None
    vapor_pressure_source: str | None = None
    baseline: VentilationTier
    worst_case: VentilationTier
    risk_tier: OccupationalTier | None = None
    assumptions: list[str] = Field(default_factory=list[str])
    warnings: list[str] = Field(default_factory=list[str])


class CdrSector(ContractModel):
    """The TSCA CDR industrial sector of a NAICS code, with the table row that matched."""

    code: str
    name: str
    matched_naics_prefix: str
    naics_edition: str


class OperationalProfile(ContractModel):
    """How a facility operates and where it sits in the TSCA framework.

    Attributes:
        life_cycle_stage: TSCA stages of the activities the facility reported to TRI.
        cou_category: TSCA condition-of-use categories of those activities.
        cdr_sector: CDR industrial sector of its NAICS code; None when the table has none.
        days_per_week: Derived from the Census QPC hours per week and a configured working day.
        operating_days_per_year: Days a year, d/yr.
        hours_per_day: Hours a day, h/day.
        annual_operating_hours: Hours a year, h/yr (at most 8,760).
        schedule_source: Where the hours come from.
    """

    naics_code: str | None = None
    life_cycle_stage: list[str] = Field(default_factory=list[str])
    cou_category: list[str] = Field(default_factory=list[str])
    cdr_sector: CdrSector | None = None
    days_per_week: int | None = None
    operating_days_per_year: float | None = None
    hours_per_day: float | None = None
    annual_operating_hours: float | None = None
    schedule_source: str | None = None
    warnings: list[str] = Field(default_factory=list[str])


class ScenarioFactor(ContractModel):
    """One factor of a worst-case scenario: a value a tool returned, or why there is none.

    Attributes:
        group: source, release, conditions or receptor_model.
        value: A number or text a tool returned; None when none did (see ``reason``).
        unit: Unit of ``value``; empty when unitless or text.
        source: Where the value came from, when a tool said.
        reason: Why there is no value.
    """

    key: str
    group: Literal["source", "release", "conditions", "receptor_model"]
    label: str
    value: float | str | None = None
    unit: str = ""
    source: str | None = None
    reason: str | None = None


class ScenarioReceptor(ContractModel):
    """A receptor of a worst-case scenario: a census tract, or the facility's workers.

    Attributes:
        residents: Persons in the tract (the tract's ACS estimate); None for workers.
        age_distribution: Age band -> percent of the tract; empty for workers.
        distance_m: Meters from the facility to the tract's internal point.
        bearing_deg: Degrees clockwise from north from the facility to that point.
        latitude: Decimal degrees of that point (the census service's internal point), for drawing.
        longitude: Decimal degrees of that point.
        concentration: Annual-average ug/m^3 the scenario gives at the tract (workers: the
            8-hour average, mg/m^3).
        fraction_of_maximum: That concentration over the scenario's maximum, unitless.
    """

    kind: Literal["tract", "workers"]
    label: str
    residents: int | None = None
    age_distribution: dict[str, float] = Field(default_factory=dict[str, float])
    distance_m: float | None = None
    bearing_deg: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    concentration: float | None = None
    fraction_of_maximum: float | None = None
    note: str | None = None


class WorstCaseScenario(ContractModel):
    """The combination of factors behind the high-end value of one quantity on one pathway.

    A screening result, never a regulatory finding: ``tier`` is the level the assessment gave.

    Attributes:
        pathway_key: Which pathway produced it, e.g. ``community_inhalation``.
        pathway: Medium, route and receptor class, in words.
        quantity: ``hq``, ``cancer_risk`` or ``oel_ratio``.
        value: The high-end value, unitless.
        tier: The level the assessment gave the value; None when none was given.
        benchmark: The level of concern the value was compared with, unitless.
        receptors_note: Why there are no receptors, or what was left out.
    """

    pathway_key: str
    pathway: str
    quantity: str
    quantity_label: str
    value: float
    tier: str | None = None
    benchmark: float | None = None
    factors: list[ScenarioFactor] = Field(default_factory=list[ScenarioFactor])
    receptors: list[ScenarioReceptor] = Field(default_factory=list[ScenarioReceptor])
    receptors_note: str | None = None
    notes: list[str] = Field(default_factory=list[str])


class ScenarioDriver(ContractModel):
    """The assessed facility whose scenario has the highest value of a pathway's quantity.

    Attributes:
        stack_number: The stack behind the value (community pathways); None otherwise.
    """

    pathway_key: str
    quantity: str
    frs_id: str
    facility_name: str | None = None
    stack_number: int | None = None
    value: float


class Facility(ContractModel):
    """One facility of the emissions inventory with what the other tools reported about it.

    Attributes:
        doc_ctrl_num: TRI document control number (the inventory has no TRI facility ID).
        total_release: Annual quantity in ``release_unit``, as reported.
        emission_rate_g_s: Total release averaged over ``operating_hours_per_year``.
        operating_hours_source: Where those hours came from (industry survey or default); None
            when the record predates the field.
        fugitive_release_kg_per_year: TRI fugitive air release, kg/yr; None when TRI has none.
        exposure: The community (ambient fenceline) result.
        occupational_exposure: The worker screening; None when no assessment produced it.
        operational_profile: Schedule, life cycle stage, condition of use and CDR sector.
        scenarios: The worst-case scenarios of the facility, one per pathway and quantity that
            has a value.
        exposure_graph: How the worst-case exposure arises, source to endpoint, per pathway.
        naics_subsector: First three digits of the inventory's NAICS code (e.g. "325").
        naics_subsector_title: That subsector's title from the Census lists; None if unknown.
        conditions_of_use: TSCA conditions of use of the activities the facility reported to TRI.
        lifecycle_stages: The distinct TSCA life cycle stages of ``conditions_of_use``.
        conditions_note: Why ``conditions_of_use`` is empty; None when it is not.
        stack_source: Where the NEI stack lookup came from, when one was made for the facility.
        status: Worst-case risk status (from the screening value when screened out); None
            while no risk is computed.
        screening: How the batch assessment screened it; None when it did not.
        buffer: The receptor radius drawn as a circle around the facility, when receptors exist.
        sector: Schematic downwind sector (toward ``wind_toward_deg``, length the receptor radius);
            never a modelled plume footprint. Present with both receptors and meteorology.
    """

    frs_id: str
    name: str | None = None
    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    zip_code: str | None = None
    latitude: float
    longitude: float
    cas_number: str | None = None
    doc_ctrl_num: str | None = None
    naics_subsector: str | None = None
    naics_subsector_title: str | None = None
    medium: str
    reporting_year: int
    total_release: float
    release_unit: str
    emission_rate_g_s: float
    operating_hours_per_year: float
    operating_hours_source: str | None = None
    fugitive_release_kg_per_year: float | None = None
    fugitive_reporting_year: int | None = None
    conditions_of_use: list[ConditionOfUse] = Field(default_factory=list[ConditionOfUse])
    lifecycle_stages: list[str] = Field(default_factory=list[str])
    conditions_note: str | None = None
    industry: Industry | None = None
    stacks: list[Stack] = Field(default_factory=list[Stack])
    receptors: Receptors | None = None
    meteorology: Meteorology | None = None
    exposure: ExposureRanges | None = None
    occupational_exposure: OccupationalExposure | None = None
    operational_profile: OperationalProfile | None = None
    scenarios: list[WorstCaseScenario] = Field(default_factory=list[WorstCaseScenario])
    exposure_graph: ExposureGraph | None = None
    status: Status | None = None
    screening: Screening | None = None
    buffer: Polygon | None = None
    sector: Polygon | None = None


class Extremum(ContractModel):
    """The highest value of one risk quantity over every attributed facility.

    Attributes:
        value: The value (HQ and cancer risk are unitless).
        frs_id: Facility whose stack gave it.
        facility_name: That facility's name, as reported.
        stack_number: The stack that gave it.
        status: Position against the configured thresholds of concern.
    """

    value: float
    frs_id: str
    facility_name: str | None = None
    stack_number: int
    status: Status


class RiskSummary(ContractModel):
    """Highest worst-case and representative HQ and cancer risk; ``reason`` when none exists."""

    hq_worst: Extremum | None = None
    cancer_risk_worst: Extremum | None = None
    hq_representative: Extremum | None = None
    cancer_risk_representative: Extremum | None = None
    reason: str | None = Field(default=None, description="Why no value yet, e.g. not computed.")


class WorkerExtremum(ContractModel):
    """The highest value of one worker quantity over the assessed facilities.

    ``risk_tier`` is the tier the tool gave that facility (baseline ventilation).
    """

    value: float
    frs_id: str
    facility_name: str | None = None
    risk_tier: OccupationalTier | None = None


class WorkerTierSummary(ContractModel):
    """Highest limit ratio, hazard quotient and cancer risk of the workers for one tier."""

    oel_ratio: WorkerExtremum | None = None
    hq: WorkerExtremum | None = None
    cancer_risk: WorkerExtremum | None = None


class WorkerRiskSummary(ContractModel):
    """The worker screening across facilities, for both ventilation tiers; ``reason`` if none."""

    baseline: WorkerTierSummary = Field(default_factory=WorkerTierSummary)
    worst_case: WorkerTierSummary = Field(default_factory=WorkerTierSummary)
    reason: str | None = Field(default=None, description="Why no value yet, e.g. not computed.")


class ReadAcross(ContractModel):
    """The read-across outcome for the queried chemical (surrogate values are scores 0-1)."""

    kind: ProvenanceKind = "not_evaluated"
    surrogate_cas: str | None = None
    surrogate_name: str | None = None
    hybrid_score: float | None = None
    cosine_similarity: float | None = None
    tanimoto_similarity: float | None = None
    within_applicability_domain: bool | None = None
    warnings: list[str] = Field(default_factory=list[str])


class Chemical(ContractModel):
    """The chemical as queried, with its properties and read-across provenance.

    Attributes:
        cas_number: CAS number as queried.
        name: The name the properties result gave (CompTox's preferred name); None when it
            gave none, and then the CAS number stands alone.
        molecular_weight_g_mol: Molecular weight, g/mol.
        vapor_pressure_mmhg: Vapor pressure, mmHg (its source is in ``sources``).
        density_g_cm3: Density, g/cm³.
        oel_twa_mg_m3: 8-hour occupational exposure limit, mg/m³ (source under ``oel_twa``).
        rfc_mg_m3: Inhalation reference concentration, mg/m³.
        iur_per_ug_m3: Inhalation unit risk, (µg/m³)⁻¹.
        sources: Field name -> source the value came from.
    """

    cas_number: str | None = None
    name: str | None = None
    molecular_weight_g_mol: float | None = None
    vapor_pressure_mmhg: float | None = None
    density_g_cm3: float | None = None
    oel_twa_mg_m3: float | None = None
    rfc_mg_m3: float | None = None
    iur_per_ug_m3: float | None = None
    sources: dict[str, str] = Field(default_factory=dict[str, str])
    read_across: ReadAcross = Field(default_factory=ReadAcross)
    warnings: list[str] = Field(default_factory=list[str])


class Unattributed(ContractModel):
    """A result that could not be tied to exactly one facility, and why."""

    tool: str
    reason: str


class BoundingBox(ContractModel):
    """Extent of the placed facilities and buffers, decimal degrees (WGS84)."""

    west: float
    south: float
    east: float
    north: float


class WorkspaceState(ContractModel):
    """The current workspace of one thread.

    Attributes:
        framing_version: Increases only when the set of placed facilities or buffers changes.
        bounds: Extent of the placed facilities and buffers; None when none is placed.
        facilities: One per FRS ID, in the order first reported.
        selected_frs_id: Facility whose receptors the ribbon shows (the highest risk, or the
            only one); None when no single facility stands out.
        chemical: The queried chemical and its provenance.
        risk: Highest risk values across the attributed facilities.
        worker_risk: Highest worker (occupational) values across the assessed facilities.
        scenario_drivers: For each pathway and quantity, the facility with the highest value.
        receptors: Receptors of the selected facility.
        meteorology: Meteorology of the selected facility, else the latest result.
        unattributed: Results not attached to any facility.
        warnings: Results left out (malformed, unattributable) and why.
    """

    framing_version: int = Field(default=0, ge=0)
    bounds: BoundingBox | None = None
    facilities: list[Facility] = Field(default_factory=list[Facility])
    selected_frs_id: str | None = None
    chemical: Chemical = Field(default_factory=Chemical)
    risk: RiskSummary = Field(default_factory=RiskSummary)
    worker_risk: WorkerRiskSummary = Field(default_factory=WorkerRiskSummary)
    scenario_drivers: list[ScenarioDriver] = Field(default_factory=list[ScenarioDriver])
    receptors: Receptors | None = None
    meteorology: Meteorology | None = None
    unattributed: list[Unattributed] = Field(default_factory=list[Unattributed])
    warnings: list[str] = Field(default_factory=list[str])
