"""The measured evidence: OSHA's air samples of the chemical in the facility's industry."""

from __future__ import annotations

from commons.cas import format_cas
from tools.assessment.helpers.monitoring.cehd import MonitoringResult, lookup
from tools.assessment.helpers.occupational.workplace import Sources, Workplace
from tools.schemas import MonitoringSummary, OperationalProfile

NO_CAS = (
    "No monitoring data: the chemical has no valid CAS number and OSHA's data are matched by "
    "CAS number only."
)


def look_up(
    workplace: Workplace,
    profile: OperationalProfile,
    sources: Sources,
) -> MonitoringResult:
    """OSHA's samples for the chemical (by a validated CAS number) and the facility's NAICS code."""
    cas = format_cas(workplace.cas) if workplace.cas else None
    if cas is None:
        return MonitoringResult(available=False, reason=NO_CAS)
    naics = profile["naics_code"] or ""
    return lookup(
        cas,
        naics,
        workplace.molecular_weight,
        sources.osha_settings,
        sources.monitoring,
    )


def summary_of(found: MonitoringResult) -> MonitoringSummary | None:
    """The result as the worker result carries it; None when no values were returned."""
    if not found.available:
        return None
    return MonitoringSummary(
        imis_code=found.imis_code,
        naics_level=found.naics_level,
        level_note=found.level_note,
        n_values=found.n_values,
        n_nondetect=found.n_nondetect,
        median_mg_m3=found.median_mg_m3,
        p95_mg_m3=found.p95_mg_m3,
        original_unit=found.original_unit,
        unit_note=found.unit_note,
        first_year=found.first_year,
        last_year=found.last_year,
        reason=found.reason,
        source=found.source,
        statements=list(found.statements),
    )
