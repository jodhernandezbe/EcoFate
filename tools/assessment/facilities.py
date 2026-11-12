"""Batch facility assessment tool: the whole exposure chain for every listed facility, in code."""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from commons.cas import format_cas
from config.assessment import AssessmentSettings, get_assessment_settings
from config.occupational import get_occupational_settings
from config.read_across import get_read_across_settings
from tools.assessment.helpers.chain import Refined, assess_all, refine_all, worst_case_only
from tools.assessment.helpers.occupational import Workplace, no_limits
from tools.assessment.helpers.scenarios import drivers_of
from tools.assessment.helpers.screened_workers import with_workers
from tools.assessment.helpers.screening import can_screen, unit_bound
from tools.assessment.helpers.steps import Steps
from tools.assessment.helpers.tiers import Screen, Split, screen, split
from tools.assessment.helpers.view import Findings, assessment_view
from tools.assessment.helpers.worker_only import assess_worker_only
from tools.emissions.helpers.inventory.lookup import TriReadError
from tools.emissions.industry import fetch_facility_industry
from tools.emissions.inventory import inventory_listing, with_eis_ids
from tools.emissions.process import lookup_scc_process_description, prefetch_scc_descriptions
from tools.emissions.stack import fetch_stack_parameters_from_nei, fetch_stack_parameters_from_scc
from tools.exposure.meteorology import get_meteorological_boundary
from tools.exposure.metrics import calculate_exposure_metrics
from tools.exposure.population import get_population_receptors
from tools.informatics.properties import fetch_chemical_properties
from tools.informatics.read_across import find_tri_read_across_surrogate
from tools.schemas import (
    AssessmentArtifact,
    AssessmentResult,
    ChemicalProperties,
    EmissionRecord,
    FacilityAssessment,
    FacilityExposure,
    Meteorology,
    NeiStackResult,
    NotAssessed,
    Population,
    ReadAcrossMatch,
    SccLookupResult,
    ScreenedOut,
    StackParameters,
    Toxicity,
    WorkerOnlyFacility,
)
from tools.tri_categories import Category, get_category_index

logger = logging.getLogger(__name__)
Outcome = tuple[AssessmentResult, AssessmentArtifact]
# The SCC index (a Chroma store opened on first use) is not safe to open or search from
# several threads at once, so the facilities take turns for that one step.
_SCC_LOCK = threading.Lock()


def _scc(title: str) -> SccLookupResult:
    with _SCC_LOCK:
        return lookup_scc_process_description.invoke({"naics_description": title})


def _nei(frs_id: str, eis_ids: list[str]) -> NeiStackResult:
    return fetch_stack_parameters_from_nei.invoke({"frs_id": frs_id, "eis_ids": eis_ids})


def _weather(latitude: float, longitude: float, year: int | None) -> Meteorology:
    args = {"latitude": latitude, "longitude": longitude, "reporting_year": year}
    return get_meteorological_boundary.invoke(args)


def _people(latitude: float, longitude: float, radius_km: float | None) -> Population:
    args = {"latitude": latitude, "longitude": longitude, "radius_km": radius_km}
    return get_population_receptors.invoke(args)


def _exposure(
    rate: float,
    stacks: list[StackParameters],
    weather: Meteorology,
    people: Population,
    toxicity: Toxicity,
) -> FacilityExposure:
    args = {
        "emission_rate": rate,
        "stacks": stacks,
        "meteorology": weather,
        "population": people,
        "toxicity": toxicity,
    }
    return calculate_exposure_metrics.invoke(args)


def default_steps() -> Steps:
    """Each step is the single tool it stands for (the edge where they are wired)."""
    return Steps(
        nei=_nei,
        industry=lambda doc: fetch_facility_industry.invoke({"doc_ctrl_num": doc}),
        scc=_scc,
        prefetch=prefetch_scc_descriptions,
        pstk=lambda scc: fetch_stack_parameters_from_scc.invoke({"scc_code": scc}),
        weather=_weather,
        people=_people,
        exposure=_exposure,
    )


def _given(
    cas: str,
    given: Toxicity,
    config: RunnableConfig | None,
) -> tuple[Toxicity, str, list[str], ChemicalProperties | None]:
    """The benchmarks passed in; the chemical is still looked up for its workplace information.

    A lookup that cannot be made (no CompTox key) leaves the worker screening without limits and
    says so; it never stops an assessment whose benchmarks were given.
    """
    values = Toxicity(rfc=given.get("rfc"), iur=given.get("iur"))
    try:
        found = fetch_chemical_properties.invoke({"cas_number": cas}, config)
    except RuntimeError as error:
        return values, "given", [f"the chemical's limits could not be looked up: {error}"], None
    return values, "given", [], found


def _toxicity(
    cas: str,
    given: Toxicity | None,
    config: RunnableConfig | None = None,
) -> tuple[Toxicity, str, list[str], ChemicalProperties | None]:
    """The benchmarks passed in, else the chemical's own from CompTox, with the properties read.

    Only the benchmark warnings are kept, unless both benchmarks are missing: then every
    warning is kept, since one of them may say why (CompTox unreachable, CAS not found). The
    run's configuration carries the values the user entered, so they reach the lookup.
    """
    if given is not None:
        return _given(cas, given, config)
    found = fetch_chemical_properties.invoke({"cas_number": cas}, config)
    warnings = list(found["warnings"])
    if found["rfc"] is not None or found["iur"] is not None:  # else every warning may say why
        warnings = [w for w in warnings if "rfc" in w.lower() or "iur" in w.lower()]
    return Toxicity(rfc=found["rfc"], iur=found["iur"]), "CompTox", warnings, found


_COMPTOX_PRESSURE = ("experimental", "predicted")


def _property_source(found: ChemicalProperties, field: str) -> str | None:
    source = (found.get("sources") or {}).get(field)
    if source is None:
        return None
    return (
        f"CompTox ({source})"
        if field == "vapor_pressure" and source in _COMPTOX_PRESSURE
        else source
    )


def _workplace(found: ChemicalProperties | None, cas: str) -> Workplace:
    """What the worker screening needs about the chemical (limits, properties), as resolved."""
    settings = get_occupational_settings()
    if found is None:
        limits = no_limits("benchmarks were given, so the chemical's limits were not looked up")
        return Workplace(settings, limits, cas, None, None, None, None)
    limits = found.get("occupational_limits") or no_limits("no limits were read")
    return Workplace(
        settings,
        limits,
        cas,
        found.get("molecular_weight"),
        _property_source(found, "molecular_weight"),
        found.get("vapor_pressure"),
        _property_source(found, "vapor_pressure"),
    )


def _once_per_title(scc: Callable[[str], SccLookupResult]) -> Callable[[str], SccLookupResult]:
    """The SCC search, made once per industry title in a call (facilities share titles)."""
    found: dict[str, SccLookupResult] = {}
    lock = threading.Lock()

    def lookup(title: str) -> SccLookupResult:
        with lock:
            if title not in found:
                found[title] = scc(title)
            return copy.deepcopy(found[title])

    return lookup


def _chosen(
    records: list[EmissionRecord],
    frs_ids: list[str],
    worker_ids: frozenset[str] = frozenset(),
) -> tuple[list[EmissionRecord], list[NotAssessed]]:
    """The stack facilities asked for that are in the inventory, and those that are not.

    A fugitive-only facility asked for (``worker_ids``) is neither: it has a worker result only.
    """
    wanted = list(dict.fromkeys(i.strip() for i in frs_ids if i.strip()))
    by_id = {r["frs_id"]: r for r in records}
    skipped = [
        NotAssessed(frs_id=i, reason="not in the inventory of this chemical (and place)")
        for i in wanted
        if i not in by_id and i not in worker_ids
    ]
    return [by_id[i] for i in wanted if i in by_id], skipped


def _resolved(records: list[EmissionRecord]) -> list[EmissionRecord]:
    """The records, with EIS IDs looked up for any that were never looked up (beyond the list)."""
    unresolved = [r for r in records if not r["eis_ids"] and r["eis_note"] is None]
    if not unresolved:
        return records
    found = {r["frs_id"]: r for r in with_eis_ids(unresolved)}
    return [found.get(r["frs_id"], r) for r in records]


@dataclass(frozen=True)
class _Call:
    """What every path of one call shares."""

    cas: str
    records: list[EmissionRecord]
    toxicity: Toxicity
    source: str
    warnings: list[str]
    radius_km: float | None
    steps: Steps
    settings: AssessmentSettings
    workplace: Workplace
    worker_ids: frozenset[str] = frozenset()


def _up_to_cap(
    call: _Call,
    refined: list[Refined],
) -> tuple[list[FacilityAssessment], list[FacilityAssessment]]:
    """The first ``max_facilities`` through the full chain; the rest at the worst case only."""
    cap = call.settings.max_facilities
    args = (call.toxicity, call.radius_km, call.steps, call.settings)
    full = assess_all(refined[:cap], *args, call.workplace)
    worst = [
        worst_case_only(i, call.radius_km, call.workplace, call.toxicity) for i in refined[cap:]
    ]
    return full, worst


def _by_id(call: _Call, frs_ids: list[str]) -> Findings:
    """The facilities asked for, without screening: the first ``max_facilities`` fully assessed."""
    chosen, skipped = _chosen(call.records, frs_ids, call.worker_ids)
    candidates = [(r, None) for r in _resolved(chosen)]
    refined = refine_all(candidates, call.toxicity, call.steps, call.settings)
    full, worst = _up_to_cap(call, refined)
    tox = (call.toxicity, call.source)
    return Findings(
        call.cas,
        tox,
        len(call.records),
        full,
        worst,
        [],
        None,
        True,
        skipped,
        call.warnings,
    )


def _refined(call: _Call, first: Screen, possible: bool) -> Split:
    """Tier 2: the candidates' own stacks and worst case, then who goes on to the full chain."""
    resolved = _resolved([record for record, _ in first.candidates])
    candidates = [(r, bound) for r, (_, bound) in zip(resolved, first.candidates, strict=True)]
    refined = refine_all(candidates, call.toxicity, call.steps, call.settings)
    return split(refined, possible, call.settings)


def _bound_warning(over: list[NotAssessed], bound: int) -> list[str]:
    if not over:
        return []
    return [f"{len(over)} facilities beyond the safety bound of {bound} were not assessed"]


def _with_workers(call: _Call, first: Screen, tiers: Split) -> list[ScreenedOut]:
    """Every screened-out facility, with its worker screening: the screen is a community one."""
    out = [*first.screened_out, *tiers.screened_out]
    return with_workers(out, call.toxicity, call.workplace)


def _found(call: _Call, possible: bool, first: Screen, tiers: Split) -> Findings:
    """Tier 3 and the record of it all: the full chain for the riskiest, the rest kept."""
    s = call.settings
    full = assess_all(tiers.full, call.toxicity, call.radius_km, call.steps, s, call.workplace)
    worst = [
        worst_case_only(i, call.radius_km, call.workplace, call.toxicity) for i in tiers.worst_only
    ]
    return Findings(
        cas=call.cas,
        toxicity=(call.toxicity, call.source),
        found=len(call.records),
        full=full,
        worst_only=worst,
        screened_out=_with_workers(call, first, tiers),
        thresholds=s.screening,
        possible=possible,
        skipped=first.over,
        warnings=[*call.warnings, *_bound_warning(first.over, s.max_refined)],
    )


def _screened(call: _Call) -> Findings:
    """Every facility screened; the ones that may matter refined, the riskiest assessed."""
    s = call.settings
    unit = unit_bound(call.steps, call.toxicity, s.screening.ambient_temperatures_k)
    possible = can_screen(unit)
    first = screen(call.records, unit if possible else None, s)
    return _found(call, possible, first, _refined(call, first, possible))


def _artifact(f: Findings) -> AssessmentArtifact:
    assessed = [*f.full, *f.worst_only]
    return AssessmentArtifact(
        assessed=assessed,
        screened_out=list(f.screened_out),
        not_assessed=list(f.skipped),
        worker_only=list(f.worker_only),
        worker_only_left_out=f.worker_only_left_out,
        drivers=drivers_of(assessed),
    )


def _has_benchmark(tox: Toxicity) -> bool:
    return tox["rfc"] is not None or tox["iur"] is not None


def _out_of_domain_note(cas: str, match: ReadAcrossMatch) -> str:
    return (
        f"{cas} has no benchmark of its own; the nearest TRI chemical "
        f"{match['surrogate_tri_cas']} scores {match['hybrid_read_across_score']} against an "
        f"applicability-domain threshold of {_threshold()}, so it was not used as a stand-in"
    )


def _estimate_note(cas: str, analogue: str, match: ReadAcrossMatch) -> str:
    return (
        f"the benchmarks are a read-across estimate from {analogue} ({match['surrogate_name']}), "
        f"a structural analogue (hybrid score {match['hybrid_read_across_score']}, "
        f"applicability-domain threshold {_threshold()}); they are not measured values for "
        f"{cas}. The analogue's molecular-weight scaling factor ({match['mw_scaling_factor']}) "
        "was not applied"
    )


def _stand_in(
    cas: str,
    analogue: str,
    match: ReadAcrossMatch,
    warnings: list[str],
) -> tuple[Toxicity, str, list[str]] | None:
    """The analogue's benchmarks with their label and note, or None if it has none."""
    found = fetch_chemical_properties.invoke({"cas_number": analogue})
    values = Toxicity(rfc=found["rfc"], iur=found["iur"])
    if not _has_benchmark(values):
        return None
    label = f"read-across from {analogue}, hybrid score {match['hybrid_read_across_score']}"
    return values, label, [*warnings, _estimate_note(cas, analogue, match)]


def _analogue_toxicity(
    cas: str,
    tox: Toxicity,
    source: str,
    warnings: list[str],
) -> tuple[Toxicity, str, list[str]]:
    """When the chemical has no benchmark of its own, the nearest TRI analogue's, if in domain.

    The analogue's values are used as they are (its molecular-weight scaling factor is only
    reported, as the read-across tool does), are labelled with the analogue, its hybrid score
    and the applicability-domain threshold, and the result says they are estimates.
    """
    if source != "CompTox" or _has_benchmark(tox):
        return tox, source, warnings
    match = find_tri_read_across_surrogate.invoke({"cas_number": cas})
    analogue = match["surrogate_tri_cas"]
    if analogue is None or match["resolution_method"] != "hybrid_read_across":
        return tox, source, warnings
    if not match["within_applicability_domain"]:
        return tox, source, [*warnings, _out_of_domain_note(cas, match)]
    return _stand_in(cas, analogue, match, warnings) or (tox, source, warnings)


def _threshold() -> float:
    return get_read_across_settings().min_hybrid_score


def _keep_larger(
    found: dict[tuple[str, str], EmissionRecord],
    records: list[EmissionRecord],
) -> int:
    """Add each record to ``found`` (one per facility and medium, the larger release kept).

    Returns:
        How many of ``records`` were already in ``found``, i.e. shared with another category.
    """
    shared = 0
    for record in records:
        key = (record["frs_id"], record["environmental_medium"])
        held = found.get(key)
        if held is None:
            found[key] = record
            continue
        shared += 1
        if record["emission_rate"] > held["emission_rate"]:
            found[key] = record
    return shared


@dataclass(frozen=True)
class _Inventory:
    """What the inventory gave: stack facilities, fugitive-only ones, how many were left out."""

    records: list[EmissionRecord]
    worker_only: list[WorkerOnlyFacility]
    left_out: int
    notes: list[str]


def _release(facility: WorkerOnlyFacility) -> float:
    release = facility["fugitive_release_kg_per_year"]
    return release if release is not None else -1.0


def _keep_larger_release(
    found: dict[str, WorkerOnlyFacility],
    facilities_: list[WorkerOnlyFacility],
) -> None:
    """Add each fugitive-only facility to ``found`` (one per facility, the larger release kept)."""
    for facility in facilities_:
        held = found.get(facility["frs_id"])
        if held is None or _release(facility) > _release(held):
            found[facility["frs_id"]] = facility


def _category_notes(cas: str, categories: Sequence[Category], shared: int) -> list[str]:
    named = "; ".join(f"{c.code} ({c.name})" for c in categories)
    notes = [
        f"{cas} has no TRI release of its own: its facilities are those of TRI category {named}, "
        "whose releases cover every member of the category together, not this chemical alone",
    ]
    if shared:
        notes.append(
            f"{shared} facility record(s) report under more than one of these categories; the "
            "larger release of each is kept",
        )
    return notes


def category_records(
    cas: str,
    place: tuple[str | None, str | None],
) -> _Inventory:
    """The facilities of the TRI categories listing ``cas``, with a note saying so (else none)."""
    categories = get_category_index().lookup(cas).categories
    if not categories:
        return _Inventory([], [], 0, [])
    found: dict[tuple[str, str], EmissionRecord] = {}
    only: dict[str, WorkerOnlyFacility] = {}
    listings = [inventory_listing(c.code, *place) for c in categories]
    shared = sum(_keep_larger(found, records) for _, records in listings)
    for result, _ in listings:
        _keep_larger_release(only, result["worker_only"])
    stacked = {frs_id for frs_id, _ in found}
    notes = _category_notes(cas, categories, shared)
    kept = sorted((w for i, w in only.items() if i not in stacked), key=_release, reverse=True)
    left_out = sum(result["worker_only_left_out"] for result, _ in listings)
    return _Inventory(list(found.values()), kept, left_out, notes)


def _inventory(
    cas: str,
    place: tuple[str | None, str | None],
) -> _Inventory:
    """The chemical's own TRI facilities; if TRI has none, those of its categories."""
    result, own = inventory_listing(cas, *place)
    if own or result["worker_only"]:
        return _Inventory(own, result["worker_only"], result["worker_only_left_out"], [])
    return category_records(cas, place)


def _worker_side(
    inventory: _Inventory,
    frs_ids: list[str] | None,
) -> list[WorkerOnlyFacility]:
    """The fugitive-only facilities to assess: all of them, or only those asked for by ID."""
    if not frs_ids:
        return inventory.worker_only
    wanted = {i.strip() for i in frs_ids}
    return [w for w in inventory.worker_only if w["frs_id"] in wanted]


def run_assessment(
    cas_number: str,
    frs_ids: list[str] | None,
    place: tuple[str | None, str | None],
    radius_km: float | None,
    toxicity: Toxicity | None,
    steps: Steps,
    config: RunnableConfig | None = None,
) -> Outcome:
    """Screen (or select) the facilities, get the benchmarks, run the tiers, build both views.

    If TRI cannot be read, nothing is assessed and the result says the assessment was not
    completed: a failed read is never taken for "no releases", so no category is substituted.
    """
    try:
        return _assess(cas_number, frs_ids, place, radius_km, toxicity, steps, config)
    except TriReadError as exc:
        return _not_completed(cas_number, str(exc))


def _not_completed(cas_number: str, reason: str) -> Outcome:
    """The outcome of an assessment that could not read TRI: no facility assessed or ruled out."""
    settings = get_assessment_settings()
    warning = (
        f"the assessment of {cas_number.strip()} was not completed because {reason}; no facility "
        "was assessed or ruled out. Retry when TRI is available"
    )
    empty = (Toxicity(rfc=None, iur=None), "none")
    f = Findings(format_cas(cas_number), empty, 0, [], [], [], None, True, [], [warning])
    view = assessment_view(f, settings.max_worst_case_listed, settings.max_screened_out_listed)
    return view, _artifact(f)


def _with_worker_only(
    findings: Findings,
    inventory: _Inventory,
    frs_ids: list[str] | None,
    call: _Call,
) -> Findings:
    """The findings plus the fugitive-only facilities: a worker result each, nothing community.

    Facilities asked for by ID are the only ones assessed, so nothing was "left out" then.
    """
    chosen = _worker_side(inventory, frs_ids)
    worker = assess_worker_only(chosen, call.toxicity, call.workplace)
    return replace(
        findings,
        worker_only=worker,
        worker_only_left_out=0 if frs_ids else inventory.left_out,
    )


def _invalid_cas(cas_number: str) -> Outcome:
    """The outcome for text that is not a CAS number: nothing assessed, and the result says so."""
    settings = get_assessment_settings()
    warning = f"{cas_number!r} is not a valid CAS registry number; nothing was assessed"
    empty = (Toxicity(rfc=None, iur=None), "none")
    f = Findings(None, empty, 0, [], [], [], None, True, [], [warning])
    view = assessment_view(f, settings.max_worst_case_listed, settings.max_screened_out_listed)
    return view, _artifact(f)


def _call_of(
    cas: str,
    inventory: _Inventory,
    benchmarks: tuple[Toxicity, str, list[str]],
    found: ChemicalProperties | None,
    run: tuple[float | None, Steps, AssessmentSettings],
) -> _Call:
    """What every path of this call shares, from the inventory, benchmarks and run settings."""
    toxicity, source, warnings = benchmarks
    radius_km, steps, settings = run
    return _Call(
        cas,
        inventory.records,
        toxicity,
        source,
        warnings,
        radius_km,
        steps,
        settings,
        _workplace(found, cas),
        frozenset(w["frs_id"] for w in inventory.worker_only),
    )


def _assess(
    cas_number: str,
    frs_ids: list[str] | None,
    place: tuple[str | None, str | None],
    radius_km: float | None,
    toxicity: Toxicity | None,
    steps: Steps,
    config: RunnableConfig | None = None,
) -> Outcome:
    settings = get_assessment_settings()
    cas = format_cas(cas_number)
    if cas is None:
        return _invalid_cas(cas_number)
    inventory = _inventory(cas, place)
    tox, source, warnings, found = _toxicity(cas, toxicity, config)
    tox, source, warnings = _analogue_toxicity(cas, tox, source, warnings)
    steps.prefetch(sorted({r["naics_title"] for r in inventory.records if r["naics_title"]}))
    steps = replace(steps, scc=_once_per_title(steps.scc))
    run = (radius_km, steps, settings)
    call = _call_of(cas, inventory, (tox, source, [*warnings, *inventory.notes]), found, run)
    findings = _by_id(call, frs_ids) if frs_ids else _screened(call)
    findings = _with_worker_only(findings, inventory, frs_ids, call)
    listed = (settings.max_worst_case_listed, settings.max_screened_out_listed)
    return assessment_view(findings, *listed), _artifact(findings)


@tool(response_format="content_and_artifact")
def assess_facilities(
    cas_number: str,
    frs_ids: list[str] | None = None,
    state: str | None = None,
    city: str | None = None,
    radius_km: float | None = None,
    toxicity: Toxicity | None = None,
    *,
    config: RunnableConfig,
) -> Outcome:
    """Screen every facility of a chemical and assess those that may matter, in one call.

    Purpose:
        Use this to assess the facilities of a chemical. It covers every facility of the
        chemical's inventory (for `state`/`city`), not only the largest emitters, in three
        tiers:
        (1) a conservative bound for each one (a generic short, cold stack, worst-case weather,
        a person at the maximum); a facility whose bound is below both thresholds (in
        `screening`) cannot reach a level of concern and is screened out; (2) the others get
        their own stacks and their worst case; those still below are screened out too;
        (3) the highest worst-case risks get the weather at the site, the residents and the
        representative case (`facilities`); the rest keep their own-stack worst case
        (`worst_case_only`). Call it once the chemical's CAS number is known (the inventory
        need not be listed first). A chemical TRI does not list on its own but reports under a
        category (`query_categories` of the read-across result) is assessed on its category's
        facilities: the result's warnings say so, and that its releases cover every member of
        the category together, not this chemical alone. When the chemical has no benchmark of
        its own, the nearest TRI analogue's are used only if it is inside the applicability
        domain; `toxicity_source` then names the analogue and its score, and the warnings say the
        values are estimates. Report both in the answer, as the result states them.
        A facility that reports only a fugitive air release and no stack release (the inventory
        lists it in `worker_only`) is a worker-only facility: nothing is released through a
        stack, so it has no community result (never zero, never a band) and is not counted among
        the screened, refined, assessed or screened-out facilities. It gets the worker screening
        and its operating profile, reported on the worker side; `worker_only_count`,
        `worker_only_left_out` and `worker_only_highest` say how many there are, how many were
        left out by the cap and which has the highest worker value. Name that one and say the
        others have the same kind of result in the dashboard; do not list them all.
        Give `frs_ids` only when the user asks about particular
        facilities: they are then fully assessed without screening. Each facility's result
        already includes its stacks, the weather at its site and the residents around it.
        Report every facility in `facilities` in the results table and every one in
        `worst_case_only` (as worst case only), not a sample or a "top N", never offer the
        rest "on request", and state the screening counts, thresholds and `note`.
        Stacks follow the order of evidence, and each facility says which was used in
        `stack_tier`: "NEI" (the facility's own stacks, every candidate evaluated as a range),
        "PSTK" (process-typical stacks of the SCC processes matching the facility's industry,
        `sccs`, evaluated as a range), or "AirToxScreen global default" (a generic short, cold
        stack, used when neither exists: results can be far higher than for the real stack;
        say so).

    Args:
        cas_number: CAS registry number as the user gave it, e.g. "110-54-3". Never a number
            recalled from a chemical's name.
        frs_ids: FRS IDs of particular facilities to assess (from the inventory); omit to
            screen every facility.
        state: Postal abbreviation, as for the inventory; omit for the whole country.
        city: City name, as for the inventory.
        radius_km: Radius to count residents in, km; omit for the default (1 mile).
        toxicity: `rfc` (mg/m3) and `iur` ((ug/m3)^-1) to use instead of the chemical's own,
            for example a read-across surrogate's values; omit to look up the chemical's.

    Returns:
        A dict with:
        - cas_number, toxicity (the rfc and iur used) and toxicity_source ("CompTox" or
          "given"); warnings say when a benchmark is missing (the matching risk is then null)
        - facilities_found: facilities in the inventory (for the place)
        - screening (null when facilities were asked for by ID): possible (false when there
          is neither an RfC nor an IUR, so nothing could be screened out), hq_threshold and
          cancer_risk_threshold (unitless), screened_out_at_bound, screened_out_with_own_stacks,
          and closest_screened_out: the screened-out facilities closest to a threshold, closest
          first (at most a few), each with frs_id, facility_name, city, state, emission_rate
          (g/s), stage ("bound" or "own stacks") and the hq and cancer_risk it was screened
          out on; when nothing was assessed, these are the results table
        - assessed: how many were fully assessed; stack_tiers: how many of them used each
          stack source
        - facilities: fully assessed, highest worst-case hazard quotient first, each with
          frs_id, facility_name, city, state, emission_rate (g/s), stack_tier,
          stacks_evaluated, sccs, industry, weather_source ("screening default" when the
          site's weather could not be read), residents and radius_km (null = 1 mile), and the
          ranges over the stacks (`low`, `high`, and the stack behind each) of concentration
          (annual average, ug/m3), hq and cancer_risk, each for the worst case and the
          representative weather (null when not computable: no benchmark, or no stack could be
          evaluated), and notes (why a better stack source could not be used, defaults, and
          the method's limits). These are the community (neighbourhood) result. Each facility
          also has worker_risk_tier ("high", "moderate" or "low", the screening priority of
          the worker indicator, not a finding) and worker_oel_ratio (the worker's 8-hour
          average over the occupational limit, unitless). They are a separate worker screening
          indicator, distinct from the community result: report them beside it and say which of
          the two drives the concern. The indicator rests on the best evidence available: first
          the measured personal air samples OSHA took in the facility's industry (the median is
          the baseline, the 95th percentile the worst case); otherwise the worker activity that
          gives the highest worst-case 8-hour average, modelled from the chemical's vapor
          pressure and molecular weight with EPA ChemSTEER defaults for the activities of the
          facility's industry and life cycle stage (and, for evaporation tasks of a very volatile
          chemical, an ECETOC TRA band estimate). The baseline is the typical case and the worst
          case the conservative one; the bands compare the 8-hour average with the occupational
          limit and the worker hazard quotient and cancer risk with the same boundaries as the
          community result, and the band is the highest of them. The activities are those a
          generic scenario of the industry describes, not observed at the facility, with no
          local exhaust ventilation or protective equipment assumed; the samples are targeted
          inspections of the industry, not of the facility. The facility's TRI fugitive air
          release is context only and enters no worker value. A null means it could not be
          computed (no measured data and no modelled activity, no vapor pressure or molecular
          weight, no occupational limit, no schedule or no benchmark): report it as not
          computed with the reason, never as zero or low. The fuller worker result (evidence,
          activities, routes, monitoring summary) and the facility's schedule, life cycle stage
          and condition of use go to the program's dashboard.
        - drivers: for each pathway (outdoor air to the general population, indoor air to
          workers) and quantity (hazard quotient, cancer risk, worker limit ratio), the facility
          with the highest value (frs_id, facility_name, value) and, for the community
          pathway, the stack behind it (stack_number). Name the driver of each result in the
          report; the combination of factors behind each value (stack configuration, weather,
          distance, the residents most affected) goes to the program's dashboard.
        - worst_case_only_count and worst_case_only: facilities still above a threshold with
          their own stacks but beyond the full-assessment cap, highest worst-case HQ first,
          each with frs_id, facility_name, city, state, emission_rate (g/s), stack_tier,
          hq_worst and cancer_risk_worst (ranges over its stacks; no weather, residents or
          representative case)
        - not_assessed: facilities asked for but not assessed, or over a cap, with the reason
        - worker_only_count: worker-only (fugitive release, no stack release) facilities; they are
          not part of `facilities_found`, `assessed` or the screening counts. worker_only_left_out:
          how many more the inventory's cap left out. worker_only_highest: the one with the
          highest worker value (the worker band, then the worst-case 8-hour average), with
          frs_id, facility_name, city, state, fugitive_release_kg_per_year (kg/yr),
          worker_risk_tier and worker_twa_worst_mg_m3 (mg/m3); null when there are none
        - note: what was screened out and assessed, in one sentence (report it)
        The worst case is the screening maximum between 100 m and 10 km, which may fall where
        no one lives. These are screening estimates, not regulatory determinations.
    """
    steps = default_steps()
    return run_assessment(cas_number, frs_ids, (state, city), radius_km, toxicity, steps, config)
