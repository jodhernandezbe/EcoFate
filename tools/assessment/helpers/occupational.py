"""The worker screening of one facility: ChemSTEER box model and RAGS Part F style dosimetry.

The facility's TRI fugitive air release is treated as generated only while the plant runs, in one
well-mixed zone, for two ventilation tiers. Every quantity that needs an input that is missing
is None with a warning; nothing is defaulted or guessed. The chemical's vapor pressure is shown
as context and only adds a warning for a non-volatile chemical; it never enters an equation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from commons.units import convert
from config.occupational import OccupationalSettings, Ventilation
from models.exposure import occupational as model
from tools.schemas import (
    EmissionRecord,
    OccupationalExposure,
    OccupationalLimits,
    OperationalProfile,
    Toxicity,
    VentilationTier,
)

ASSUMPTIONS = [
    "The fugitive release is taken as generated only while the plant runs, in one well-mixed "
    "zone (EPA ChemSTEER mass-balance box model).",
    "The two ventilation tiers are screening defaults, not this plant's ventilation.",
    "A worker is exposed for the 8-hour time-weighted average; this is not an OSHA compliance "
    "determination.",
]


@dataclass(frozen=True)
class Workplace:
    """What the worker screening needs about the chemical, beyond the facility.

    Attributes:
        settings: Ventilation tiers, breathing volumes, worker schedule and tier boundaries.
        limits: The chemical's occupational limits from PubChem (mg/m^3).
        vapor_pressure_mmhg: Vapor pressure, mmHg, or None; context only.
        vapor_pressure_source: Where it came from, or None.
    """

    settings: OccupationalSettings
    limits: OccupationalLimits
    vapor_pressure_mmhg: float | None
    vapor_pressure_source: str | None


@dataclass(frozen=True)
class _Inputs:
    release_kg: float
    days: float
    hours: float
    oel: float | None
    rfc: float | None
    iur: float | None


def _empty_tier(tier: Ventilation) -> VentilationTier:
    return VentilationTier(
        label=tier.label,
        ventilation_m3_per_s=convert(tier.rate_ft3_per_min, "ft^3/min", "m^3/s"),
        mixing_factor=tier.mixing_factor,
        workplace_concentration_mg_m3=None,
        twa_mg_m3=None,
        oel_ratio=None,
        hq=None,
        cancer_risk=None,
        risk_tier=None,
    )


def _chronic(twa: float, days: float, years: float, s: OccupationalSettings) -> float:
    worker_days = min(s.worker_days_per_year, days)
    return model.worker_average_concentration(
        twa,
        s.shift_inhalation_m3,
        s.daily_inhalation_m3,
        worker_days,
        s.tenure_years,
        years,
    )


def _risks(
    twa: float,
    inputs: _Inputs,
    s: OccupationalSettings,
) -> tuple[float | None, float | None, float | None]:
    """Limit ratio, worker hazard quotient and worker cancer risk (None without the benchmark)."""
    adc = _chronic(twa, inputs.days, s.tenure_years, s)
    ladc = _chronic(twa, inputs.days, s.lifetime_years, s)
    ratio = None if inputs.oel is None else model.oel_ratio(twa, inputs.oel)
    hq = None if inputs.rfc is None else model.worker_hazard_quotient(adc, inputs.rfc)
    risk = None if inputs.iur is None else model.worker_cancer_risk(ladc, inputs.iur)
    return ratio, hq, risk


def _classify(
    ratio: float | None,
    hq: float | None,
    risk: float | None,
    s: OccupationalSettings,
) -> str | None:
    t = s.thresholds
    return model.risk_tier(
        ratio,
        hq,
        risk,
        exceedance=(t.exceedance_ratio, t.exceedance_hq, t.exceedance_cancer_risk),
        elevated=(t.elevated_ratio, t.elevated_hq, t.elevated_cancer_risk),
    )


def _tier(tier: Ventilation, inputs: _Inputs, s: OccupationalSettings) -> VentilationTier:
    result = _empty_tier(tier)
    generation = model.generation_rate(inputs.release_kg, inputs.days, inputs.hours)
    concentration = model.workplace_concentration(
        generation,
        result["ventilation_m3_per_s"],
        tier.mixing_factor,
    )
    twa = model.twa_concentration(concentration, inputs.hours, s.twa_hours)
    ratio, hq, risk = _risks(twa, inputs, s)
    result.update(
        workplace_concentration_mg_m3=concentration,
        twa_mg_m3=twa,
        oel_ratio=ratio,
        hq=hq,
        cancer_risk=risk,
        risk_tier=_classify(ratio, hq, risk, s),
    )
    return result


def _missing(record: EmissionRecord, profile: OperationalProfile) -> list[str]:
    reasons: list[str] = []
    if record["fugitive_release_kg_per_year"] is None:
        reasons.append("TRI reports no fugitive air release for this facility")
    if profile["operating_days_per_year"] is None or profile["hours_per_day"] is None:
        reasons.append("the operating schedule could not be derived")
    return reasons


def _warnings(
    reasons: list[str],
    workplace: Workplace,
    toxicity: Toxicity,
    limits: OccupationalLimits,
) -> list[str]:
    notes = [f"worker exposure not computed: {reason}" for reason in reasons]
    if limits["oel_twa_mg_m3"] is None:
        notes.append(
            "no 8-hour occupational limit is available, so the limit ratio is not computed",
        )
    if toxicity.get("rfc") is None:
        notes.append("no RfC, so the worker hazard quotient is not computed")
    if toxicity.get("iur") is None:
        notes.append("no IUR, so the worker cancer risk is not computed")
    pressure = workplace.vapor_pressure_mmhg
    if pressure is not None and pressure <= workplace.settings.low_volatility_mmhg:
        notes.append(
            f"vapor pressure is only {pressure:g} mmHg, so a large fugitive release into "
            "workplace air is less plausible for this chemical",
        )
    return notes


def _tiers(
    inputs: _Inputs | None,
    s: OccupationalSettings,
) -> tuple[VentilationTier, VentilationTier]:
    if inputs is None:
        return _empty_tier(s.baseline), _empty_tier(s.worst_case)
    return _tier(s.baseline, inputs, s), _tier(s.worst_case, inputs, s)


def occupational_exposure(
    record: EmissionRecord,
    profile: OperationalProfile,
    toxicity: Toxicity,
    workplace: Workplace,
) -> OccupationalExposure:
    """The worker screening of ``record`` for both ventilation tiers.

    Args:
        record: The inventory record; its fugitive release (kg/yr) is the generation mass.
        profile: Its operating schedule (days per year, hours per day).
        toxicity: RfC (mg/m^3) and IUR ((ug/m^3)^-1) used for the community result too.
        workplace: The chemical's limits, vapor pressure and the screening factors.

    Returns:
        Both tiers, the headline tier (the baseline one), the inputs and the warnings.
    """
    limits = workplace.limits
    reasons = _missing(record, profile)
    inputs = None if reasons else _inputs(record, profile, toxicity, limits)
    baseline, worst = _tiers(inputs, workplace.settings)
    return OccupationalExposure(
        **_facts(record, profile, toxicity, workplace),
        baseline=baseline,
        worst_case=worst,
        risk_tier=baseline["risk_tier"],
        assumptions=list(ASSUMPTIONS),
        warnings=_warnings(reasons, workplace, toxicity, limits),
    )


class _Facts(TypedDict):
    fugitive_release_kg_per_year: float | None
    fugitive_reporting_year: int | None
    operating_days_per_year: float | None
    hours_per_day: float | None
    oel_twa_mg_m3: float | None
    oel_source: str | None
    rfc: float | None
    iur: float | None
    vapor_pressure_mmhg: float | None
    vapor_pressure_source: str | None


def _facts(
    record: EmissionRecord,
    profile: OperationalProfile,
    toxicity: Toxicity,
    workplace: Workplace,
) -> _Facts:
    limits = workplace.limits
    return _Facts(
        fugitive_release_kg_per_year=record["fugitive_release_kg_per_year"],
        fugitive_reporting_year=record["fugitive_reporting_year"],
        operating_days_per_year=profile["operating_days_per_year"],
        hours_per_day=profile["hours_per_day"],
        oel_twa_mg_m3=limits["oel_twa_mg_m3"],
        oel_source=limits["oel_source"],
        rfc=toxicity.get("rfc"),
        iur=toxicity.get("iur"),
        vapor_pressure_mmhg=workplace.vapor_pressure_mmhg,
        vapor_pressure_source=workplace.vapor_pressure_source,
    )


def _inputs(
    record: EmissionRecord,
    profile: OperationalProfile,
    toxicity: Toxicity,
    limits: OccupationalLimits,
) -> _Inputs | None:
    release = record["fugitive_release_kg_per_year"]
    days, hours = profile["operating_days_per_year"], profile["hours_per_day"]
    if release is None or days is None or hours is None:
        return None
    return _Inputs(
        release,
        days,
        hours,
        limits["oel_twa_mg_m3"],
        toxicity.get("rfc"),
        toxicity.get("iur"),
    )


def unavailable(settings: OccupationalSettings, reason: str) -> OccupationalExposure:
    """A worker result with nothing computed, for a caller that has no workplace information."""
    empty = _empty_tier(settings.baseline)
    return OccupationalExposure(
        fugitive_release_kg_per_year=None,
        fugitive_reporting_year=None,
        operating_days_per_year=None,
        hours_per_day=None,
        oel_twa_mg_m3=None,
        oel_source=None,
        rfc=None,
        iur=None,
        vapor_pressure_mmhg=None,
        vapor_pressure_source=None,
        baseline=empty,
        worst_case=_empty_tier(settings.worst_case),
        risk_tier=None,
        assumptions=list(ASSUMPTIONS),
        warnings=[f"worker exposure not computed: {reason}"],
    )


def no_limits(reason: str) -> OccupationalLimits:
    """Occupational limits with nothing in them, for a chemical that was not looked up."""
    return OccupationalLimits(
        oel_twa_mg_m3=None,
        oel_source=None,
        limits={},
        reasons={},
        warnings=[reason],
    )
