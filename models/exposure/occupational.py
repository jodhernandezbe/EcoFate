"""Worker (occupational) screening arithmetic.

Sources: U.S. EPA ChemSTEER mass-balance workplace box model (2012, 2015); OSHA 29 CFR 1910.1000
for the 8-hour time-weighted average (TWA) and its ratio to an occupational exposure limit
(OEL); EPA Risk Assessment Guidance for Superfund Part F (2009) and the TSCA Section 6 risk
evaluation approach (2024) for the chronic worker concentration, hazard quotient and cancer
risk. Screening level only, not a compliance determination.
"""

from __future__ import annotations

import math

_SECONDS_PER_HOUR = 3600.0
_MG_PER_KG = 1.0e6
_UG_PER_MG = 1000.0
_DAYS_PER_YEAR = 365.0


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite, positive number, got {value!r}")


def _non_negative(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number, got {value!r}")


def generation_rate(
    release_kg_per_year: float,
    operating_days_per_year: float,
    hours_per_day: float,
) -> float:
    """Generation rate of the chemical inside the workplace while the plant runs.

    G = E x 1e6 / (OD x H x 3600).

    Args:
        release_kg_per_year: Fugitive air release E, kg/yr; >= 0.
        operating_days_per_year: Operating days OD, days/yr; > 0.
        hours_per_day: Operating hours per day H, h/day; > 0.

    Returns:
        Generation rate G, mg/s.

    Raises:
        ValueError: If an input is not finite, the release is negative or a schedule value
            is not positive.
    """
    _non_negative(release_kg_per_year, "release_kg_per_year")
    _positive(operating_days_per_year, "operating_days_per_year")
    _positive(hours_per_day, "hours_per_day")
    seconds = operating_days_per_year * hours_per_day * _SECONDS_PER_HOUR
    return release_kg_per_year * _MG_PER_KG / seconds


def workplace_concentration(
    generation_mg_per_s: float,
    ventilation_m3_per_s: float,
    mixing_factor: float,
) -> float:
    """Steady-state air concentration of a well-mixed workplace zone.

    C = G / (Q x k).

    Args:
        generation_mg_per_s: Generation rate G, mg/s; >= 0.
        ventilation_m3_per_s: Ventilation rate Q, m^3/s; > 0.
        mixing_factor: Mixing factor k, unitless, in (0, 1].

    Returns:
        Workplace concentration, mg/m^3.

    Raises:
        ValueError: If an input is invalid.
    """
    _non_negative(generation_mg_per_s, "generation_mg_per_s")
    _positive(ventilation_m3_per_s, "ventilation_m3_per_s")
    _positive(mixing_factor, "mixing_factor")
    if mixing_factor > 1.0:
        raise ValueError(f"mixing_factor must be at most 1, got {mixing_factor!r}")
    return generation_mg_per_s / (ventilation_m3_per_s * mixing_factor)


def twa_concentration(
    concentration_mg_per_m3: float,
    hours_per_day: float,
    twa_hours: float = 8.0,
) -> float:
    """8-hour time-weighted average of the workplace concentration.

    C_TWA = C x min(H, 8) / 8.

    Args:
        concentration_mg_per_m3: Workplace concentration, mg/m^3; >= 0.
        hours_per_day: Hours the plant runs per day H, h/day; > 0.
        twa_hours: Length of the averaging day, h; > 0 (8 under OSHA).

    Returns:
        Time-weighted average, mg/m^3.

    Raises:
        ValueError: If an input is invalid.
    """
    _non_negative(concentration_mg_per_m3, "concentration_mg_per_m3")
    _positive(hours_per_day, "hours_per_day")
    _positive(twa_hours, "twa_hours")
    return concentration_mg_per_m3 * min(hours_per_day, twa_hours) / twa_hours


def oel_ratio(twa_mg_per_m3: float, oel_mg_per_m3: float) -> float:
    """Ratio of the 8-hour TWA to the occupational exposure limit (unitless).

    Args:
        twa_mg_per_m3: 8-hour TWA, mg/m^3; >= 0.
        oel_mg_per_m3: 8-hour TWA limit, mg/m^3; > 0.

    Returns:
        R_OEL; above 1 means the limit is exceeded.

    Raises:
        ValueError: If the TWA is invalid or the limit is not positive.
    """
    _non_negative(twa_mg_per_m3, "twa_mg_per_m3")
    _positive(oel_mg_per_m3, "oel_mg_per_m3")
    return twa_mg_per_m3 / oel_mg_per_m3


def worker_average_concentration(
    twa_mg_per_m3: float,
    shift_inhalation_m3: float,
    daily_inhalation_m3: float,
    worker_days_per_year: float,
    tenure_years: float,
    averaging_years: float,
) -> float:
    """Worker concentration averaged over a time, as an equivalent 24-hour concentration.

    C_w = C_TWA x (shift / daily inhalation) x (OD_w x ED) / (AT x 365). With the averaging time
    equal to the tenure this is the average daily concentration (the tenure cancels); with the
    lifetime it is the lifetime average daily concentration.

    Args:
        twa_mg_per_m3: 8-hour TWA, mg/m^3; >= 0.
        shift_inhalation_m3: Air breathed in a shift, m^3/day; > 0.
        daily_inhalation_m3: Air breathed in 24 h, m^3/day; > 0 and >= the shift value.
        worker_days_per_year: Days a worker works per year, days/yr; in (0, 365].
        tenure_years: Years of work ED, yr; > 0.
        averaging_years: Averaging time AT, yr; > 0 and >= the tenure.

    Returns:
        Averaged concentration, mg/m^3.

    Raises:
        ValueError: If an input is invalid.
    """
    _non_negative(twa_mg_per_m3, "twa_mg_per_m3")
    for name, value in (
        ("shift_inhalation_m3", shift_inhalation_m3),
        ("daily_inhalation_m3", daily_inhalation_m3),
        ("worker_days_per_year", worker_days_per_year),
        ("tenure_years", tenure_years),
        ("averaging_years", averaging_years),
    ):
        _positive(value, name)
    if shift_inhalation_m3 > daily_inhalation_m3:
        raise ValueError("shift_inhalation_m3 must not exceed daily_inhalation_m3")
    if worker_days_per_year > _DAYS_PER_YEAR or tenure_years > averaging_years:
        raise ValueError(
            "worker days must be at most 365 and the tenure at most the averaging time",
        )
    days = worker_days_per_year * tenure_years / (averaging_years * _DAYS_PER_YEAR)
    return twa_mg_per_m3 * shift_inhalation_m3 / daily_inhalation_m3 * days


def worker_hazard_quotient(
    adc_mg_per_m3: float,
    rfc_mg_per_m3: float,
) -> float:
    """Worker hazard quotient: average daily concentration over the RfC (unitless).

    Args:
        adc_mg_per_m3: Average daily concentration, mg/m^3; >= 0.
        rfc_mg_per_m3: Reference concentration RfC, mg/m^3; > 0.

    Raises:
        ValueError: If the concentration is invalid or the RfC is not positive.
    """
    _non_negative(adc_mg_per_m3, "adc_mg_per_m3")
    _positive(rfc_mg_per_m3, "rfc_mg_per_m3")
    return adc_mg_per_m3 / rfc_mg_per_m3


def worker_cancer_risk(
    ladc_mg_per_m3: float,
    iur_per_ug_m3: float,
) -> float:
    """Worker lifetime excess cancer risk: LADC (as ug/m^3) x IUR (probability).

    Args:
        ladc_mg_per_m3: Lifetime average daily concentration, mg/m^3; >= 0.
        iur_per_ug_m3: Inhalation unit risk IUR, (ug/m^3)^-1; >= 0.

    Raises:
        ValueError: If an input is invalid.
    """
    _non_negative(ladc_mg_per_m3, "ladc_mg_per_m3")
    _non_negative(iur_per_ug_m3, "iur_per_ug_m3")
    return ladc_mg_per_m3 * _UG_PER_MG * iur_per_ug_m3


def _above(value: float | None, limit: float) -> bool:
    return value is not None and value > limit


def risk_tier(
    ratio: float | None,
    hq: float | None,
    cancer_risk: float | None,
    *,
    exceedance: tuple[float, float, float],
    elevated: tuple[float, float, float],
) -> str | None:
    """Tier of the worker screening: "exceedance", "elevated", "acceptable", or None.

    Args:
        ratio: OEL ratio (unitless) or None.
        hq: Worker hazard quotient (unitless) or None.
        cancer_risk: Worker lifetime cancer risk (probability) or None.
        exceedance: Boundaries (ratio, hq, cancer risk) above which the tier is "exceedance".
        elevated: Boundaries (ratio, hq, cancer risk) above which the tier is "elevated".

    Returns:
        The tier, or None when all three quantities are None (nothing to compare).
    """
    values = (ratio, hq, cancer_risk)
    if all(v is None for v in values):
        return None
    if any(_above(v, limit) for v, limit in zip(values, exceedance, strict=True)):
        return "exceedance"
    if any(_above(v, limit) for v, limit in zip(values, elevated, strict=True)):
        return "elevated"
    return "acceptable"
