"""Facilities: the inventory records with what the other tools reported about each."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from api.schemas.workspace import (
    Dose,
    ExposureRanges,
    Extreme,
    Facility,
    Industry,
    Meteorology,
    Receptors,
    Screening,
    Status,
    Unattributed,
)
from api.services.exposure_graph import build_exposure_graph
from api.services.geometry import circle, sector
from api.services.projectors.attribution import (
    Finder,
    at_facility,
    same_doc,
    same_frs,
    same_rate,
)
from api.services.projectors.ledger import Ledger, Located, Receptor
from api.services.projectors.payloads import (
    EmissionPayload,
    ExposurePayload,
    FacilityPayload,
    IndustryPayload,
    MeteorologyPayload,
    PopulationPayload,
    RangeEntryPayload,
    StackPayload,
    WorkerOnlyFacilityPayload,
)
from api.services.projectors.rules import WorkspaceRules, cancer_status, hq_status, worse
from api.services.projectors.stacks import dose_of, facility_stacks

SCREENING_DEFAULT = "screening default"


@dataclass(frozen=True)
class Attachments:
    """The results attributed to facilities, by FRS ID."""

    industries: dict[str, tuple[str, IndustryPayload]]
    stacks: dict[str, tuple[str, list[StackPayload]]]
    receptors: dict[str, Receptor]
    weather: dict[str, Located[MeteorologyPayload]]
    exposures: dict[str, tuple[float | str, ExposurePayload]]


def _attach(ledger: Ledger, rules: WorkspaceRules, lost: list[Unattributed]) -> Attachments:
    finder = Finder(ledger.facilities, lost)
    near = at_facility(rules.coordinate_tolerance_deg)
    return Attachments(
        industries=finder.of(ledger.industries, same_doc, "fetch_facility_industry"),
        stacks=finder.of(ledger.nei, same_frs, "fetch_stack_parameters_from_nei"),
        receptors=finder.of(
            ledger.population,
            lambda item, record: near(item.point, record),
            "get_population_receptors",
        ),
        weather=finder.of(ledger.meteorology, near, "get_meteorological_boundary"),
        exposures=finder.of(ledger.exposures, same_rate, "calculate_exposure_metrics"),
    )


def _receptors(receptor: Receptor) -> Receptors:
    payload: PopulationPayload = receptor.point.payload
    return Receptors(
        total_population=payload.total_population,
        radius_km=receptor.radius_km,
        age_distribution=dict(payload.age_distribution),
        source=payload.source,
        screening_default=payload.source == SCREENING_DEFAULT,
        warnings=list(payload.warnings),
    )


def meteorology_view(
    point: Located[MeteorologyPayload],
    facility: EmissionPayload | None = None,
) -> Meteorology:
    """The tool's weather with the downwind direction, for its point and facility (if any)."""
    weather = point.payload
    return Meteorology(
        wind_speed_m_s=weather.wind_speed,
        wind_from_deg=weather.wind_direction,
        wind_toward_deg=(weather.wind_direction + 180) % 360,
        ambient_temperature_k=weather.ambient_temperature,
        stability_class=weather.stability_class,
        source=weather.source,
        screening_default=weather.source == SCREENING_DEFAULT,
        latitude=point.latitude,
        longitude=point.longitude,
        frs_id=facility.frs_id if facility else None,
        facility_name=facility.facility_name if facility else None,
        warnings=list(weather.warnings),
    )


def _extreme(entry: RangeEntryPayload | None) -> Extreme | None:
    if entry is None:
        return None
    return Extreme(
        low=entry.low,
        high=entry.high,
        low_stack=entry.low_stack,
        high_stack=entry.high_stack,
    )


def _highest_dose(payload: ExposurePayload) -> Dose | None:
    """Per age band, the largest dose any stack reported (a maximum of reported numbers)."""
    doses = [d for d in map(dose_of, payload.results) if d is not None]
    by_band = {
        band: max(d.by_band[band] for d in doses if band in d.by_band)
        for band in dict.fromkeys(b for d in doses for b in d.by_band)
    }
    if not by_band:
        return None
    top = max(by_band, key=lambda band: by_band[band])
    return Dose(highest_mg_kg_day=by_band[top], highest_band=top, by_band=by_band)


def _ranges(payload: ExposurePayload) -> ExposureRanges:
    found = payload.range
    return ExposureRanges(
        stacks_given=payload.stacks_given,
        stacks_evaluated=payload.stacks_evaluated,
        hq_worst=_extreme(found.hq if found else None),
        cancer_risk_worst=_extreme(found.cancer_risk if found else None),
        concentration_worst=_extreme(found.max_concentration if found else None),
        hq_representative=_extreme(found.representative.hq if found else None),
        cancer_risk_representative=_extreme(found.representative.cancer_risk if found else None),
        concentration_representative=_extreme(
            found.representative.max_concentration if found else None,
        ),
        dose=_highest_dose(payload),
        warnings=list(payload.warnings),
    )


def _status(ranges: ExposureRanges | None, rules: WorkspaceRules) -> Status | None:
    if ranges is None:
        return None
    hq, risk = ranges.hq_worst, ranges.cancer_risk_worst
    return worse(
        hq_status(hq.high, rules.thresholds) if hq else None,
        cancer_status(risk.high, rules.thresholds) if risk else None,
    )


def _screened_status(screening: Screening | None, rules: WorkspaceRules) -> Status | None:
    """The status of a screened-out facility, from the screening value it was left out on."""
    if screening is None:
        return None
    hq, risk = screening.value_hq, screening.value_cancer_risk
    return worse(
        hq_status(hq, rules.thresholds) if hq is not None else None,
        cancer_status(risk, rules.thresholds) if risk is not None else None,
    )


INVENTORY_SOURCE = "TRI inventory"


def _industry(
    entry: tuple[str, IndustryPayload] | None,
    record: FacilityPayload,
) -> Industry | None:
    """The industry tool's answer; else the code and title the inventory reported, if any."""
    if entry is not None:
        return Industry(**entry[1].model_dump())
    if record.naics_code is None:
        return None
    return Industry(
        naics_code=record.naics_code,
        naics_title=record.naics_title,
        source=INVENTORY_SOURCE,
    )


def _identity(record: FacilityPayload) -> dict[str, object]:
    return {
        "frs_id": record.frs_id,
        "name": record.facility_name,
        "address": record.address,
        "city": record.city,
        "county": record.county,
        "state": record.state,
        "zip_code": record.zip_code,
        "latitude": record.latitude,
        "longitude": record.longitude,
        "doc_ctrl_num": record.doc_ctrl_num,
        "naics_subsector": record.naics_subsector,
        "naics_subsector_title": record.naics_subsector_title,
    }


def _context(record: FacilityPayload, cas: str | None) -> dict[str, object]:
    """What any facility reports: year, hours, fugitive release (context) and conditions of use."""
    return {
        "cas_number": cas,
        "reporting_year": record.reporting_year,
        "operating_hours_per_year": record.operating_hours_per_year,
        "operating_hours_source": record.operating_hours_source,
        "fugitive_release_kg_per_year": record.fugitive_release_kg_per_year,
        "fugitive_reporting_year": record.fugitive_reporting_year,
        "conditions_of_use": [c.model_dump() for c in record.conditions_of_use],
        "lifecycle_stages": list(record.lifecycle_stages),
        "conditions_note": record.conditions_note,
    }


def _release(record: EmissionPayload, cas: str | None) -> dict[str, object]:
    return {
        **_context(record, cas),
        "medium": record.environmental_medium,
        "total_release": record.total_release,
        "release_unit": record.unit,
        "emission_rate_g_s": record.emission_rate,
    }


def _shapes(
    record: EmissionPayload,
    receptor: Receptor | None,
    weather: Located[MeteorologyPayload] | None,
    rules: WorkspaceRules,
) -> dict[str, object]:
    """The drawn circle (with receptors) and schematic sector (with receptors and weather)."""
    if receptor is None:
        return {"buffer": None, "sector": None}
    where, radius = (record.latitude, record.longitude), receptor.radius_km
    toward = meteorology_view(weather, record).wind_toward_deg if weather else None
    return {
        "buffer": circle(*where, radius, rules.vertex_spacing_deg),
        "sector": None
        if toward is None
        else sector(*where, toward, radius, rules.sector_half_angle_deg, rules.vertex_spacing_deg),
    }


def _model(payload: BaseModel | None) -> dict[str, object] | None:
    """A payload as the plain fields the contract model validates (None stays None)."""
    return payload.model_dump() if payload is not None else None


def _attached(
    record: EmissionPayload,
    found: Attachments,
    ledger: Ledger,
    rules: WorkspaceRules,
) -> dict[str, object]:
    frs_id = record.frs_id
    nei, exposure = found.stacks.get(frs_id), found.exposures.get(frs_id)
    receptor, weather = found.receptors.get(frs_id), found.weather.get(frs_id)
    ranges = _ranges(exposure[1]) if exposure else None
    screening = ledger.screening.get(frs_id)
    return {
        "industry": _industry(found.industries.get(frs_id), record),
        "stacks": facility_stacks(nei[1] if nei else [], exposure[1] if exposure else None, ledger),
        "receptors": _receptors(receptor) if receptor else None,
        "meteorology": meteorology_view(weather, record) if weather else None,
        "exposure": ranges,
        "occupational_exposure": _model(ledger.worker.get(frs_id)),
        "operational_profile": _model(ledger.profiles.get(frs_id)),
        "scenarios": [_model(p) for p in ledger.scenarios.get(frs_id, [])],
        "status": _status(ranges, rules) or _screened_status(screening, rules),
        "screening": screening,
        **_shapes(record, receptor, weather, rules),
    }


def _with_graph(facility: Facility, rules: WorkspaceRules) -> Facility:
    """The facility with its exposure graph, built from its own validated values."""
    return facility.model_copy(
        update={"exposure_graph": build_exposure_graph(facility, rules.graph)},
    )


def _worker_only(
    record: WorkerOnlyFacilityPayload,
    ledger: Ledger,
    rules: WorkspaceRules,
) -> Facility:
    """A fugitive-only facility: its worker result, and no community value (never zero)."""
    frs_id = record.frs_id
    reason = ledger.community_reasons.get(frs_id, rules.graph.reasons["worker_only"])
    return Facility.model_validate(
        {
            **_identity(record),
            **_context(record, ledger.facility_cas.get(frs_id)),
            "worker_only": True,
            "community_reason": reason,
            "industry": _industry(None, record),
            "occupational_exposure": _model(ledger.worker.get(frs_id)),
            "operational_profile": _model(ledger.profiles.get(frs_id)),
        },
    )


def _stack_facility(
    frs_id: str,
    record: EmissionPayload,
    found: Attachments,
    ledger: Ledger,
    rules: WorkspaceRules,
) -> Facility:
    return _with_graph(
        Facility.model_validate(
            {
                **_identity(record),
                **_release(record, ledger.facility_cas.get(frs_id)),
                **_attached(record, found, ledger, rules),
            },
        ),
        rules,
    )


def build_facilities(
    ledger: Ledger,
    rules: WorkspaceRules,
) -> tuple[list[Facility], list[Unattributed]]:
    """Every placed facility with its attributed results, and the results that fit none.

    The stack facilities come first; the fugitive-only ones follow, with a worker result only.
    """
    lost: list[Unattributed] = []
    found = _attach(ledger, rules, lost)
    facilities = [
        _stack_facility(frs_id, record, found, ledger, rules)
        for frs_id, record in ledger.facilities.items()
    ]
    only = [
        _with_graph(_worker_only(record, ledger, rules), rules)
        for frs_id, record in ledger.worker_only.items()
        if frs_id not in ledger.facilities
    ]
    return [*facilities, *only], lost
