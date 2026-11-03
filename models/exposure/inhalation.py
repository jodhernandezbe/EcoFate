"""Inhalation exposure and risk arithmetic on top of the dose and risk equations.

Sources: EPA Risk Assessment Guidance for Superfund, Part F (2009), for the exposure
concentration EC = CA x ET/24 x EF/365 x ED/AT; EPA Regional Screening Levels User's Guide for
the resident-air defaults; EPA Exposure Factors Handbook (2011) for inhalation rates and body
weights by age.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from models.exposure.dose import average_daily_dose
from models.exposure.risk import calculate_cancer_risk, calculate_hazard_quotient

_HOURS_PER_DAY = 24.0
_DAYS_PER_YEAR = 365.0
_UG_PER_MG = 1000.0


def _finite_non_negative(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number, got {value!r}")


def annual_from_one_hour(
    concentration_1h: float,
    annual_factor: float,
) -> float:
    """Annual-average concentration from a 1-hour maximum by EPA's screening factor.

    Args:
        concentration_1h: Maximum 1-hour concentration, in any concentration unit; >= 0.
        annual_factor: Multiplying factor, unitless, in (0, 1] (EPA screening procedures: 0.08).

    Returns:
        Annual-average concentration in the same unit as the input.

    Raises:
        ValueError: If the concentration is negative or the factor is outside (0, 1].
    """
    _finite_non_negative(concentration_1h, "concentration_1h")
    if (
        isinstance(annual_factor, bool)
        or not math.isfinite(annual_factor)
        or not 0 < annual_factor <= 1
    ):
        raise ValueError(f"annual_factor must be in (0, 1], got {annual_factor!r}")
    return concentration_1h * annual_factor


def exposure_concentration(
    air_concentration: float,
    exposure_time_hours_per_day: float,
    exposure_frequency_days_per_year: float,
    exposure_duration_years: float,
    averaging_time_years: float,
) -> float:
    """Exposure concentration EC = CA x (ET/24) x (EF/365) x (ED/AT) (RAGS Part F).

    Args:
        air_concentration: Ambient concentration, in any concentration unit; >= 0.
        exposure_time_hours_per_day: Hours exposed per day (h/day), 0 to 24.
        exposure_frequency_days_per_year: Days exposed per year (days/yr), 0 to 365.
        exposure_duration_years: Years of exposure (yr); > 0.
        averaging_time_years: Averaging time (yr); > 0 (equal to the duration for non-cancer
            effects, the lifetime for cancer).

    Returns:
        Exposure concentration in the unit of ``air_concentration``.

    Raises:
        ValueError: If a value is outside its range or the duration or averaging time is not
            positive.
    """
    _finite_non_negative(air_concentration, "air_concentration")
    _finite_non_negative(exposure_time_hours_per_day, "exposure_time_hours_per_day")
    _finite_non_negative(exposure_frequency_days_per_year, "exposure_frequency_days_per_year")
    if exposure_time_hours_per_day > _HOURS_PER_DAY:
        raise ValueError("exposure_time_hours_per_day must be at most 24")
    if exposure_frequency_days_per_year > _DAYS_PER_YEAR:
        raise ValueError("exposure_frequency_days_per_year must be at most 365")
    if not (math.isfinite(exposure_duration_years) and exposure_duration_years > 0):
        raise ValueError("exposure_duration_years must be positive")
    if not (math.isfinite(averaging_time_years) and averaging_time_years > 0):
        raise ValueError("averaging_time_years must be positive")
    return (
        air_concentration
        * (exposure_time_hours_per_day / _HOURS_PER_DAY)
        * (exposure_frequency_days_per_year / _DAYS_PER_YEAR)
        * (exposure_duration_years / averaging_time_years)
    )


def hazard_quotient_from_rfc(
    exposure_concentration_ug_per_m3: float,
    rfc_mg_per_m3: float,
) -> float:
    """Hazard quotient HQ = EC / RfC with EC in ug/m^3 and the RfC in mg/m^3.

    Raises:
        ValueError: If the exposure concentration is negative or the RfC is not positive.
    """
    _finite_non_negative(exposure_concentration_ug_per_m3, "exposure_concentration_ug_per_m3")
    if not (math.isfinite(rfc_mg_per_m3) and rfc_mg_per_m3 > 0):
        raise ValueError("rfc_mg_per_m3 must be positive")
    return calculate_hazard_quotient(exposure_concentration_ug_per_m3, rfc_mg_per_m3 * _UG_PER_MG)


def cancer_risk_from_iur(
    exposure_concentration_ug_per_m3: float,
    iur_per_ug_per_m3: float,
) -> float:
    """Lifetime excess cancer risk = EC (ug/m^3) x IUR ((ug/m^3)^-1).

    Raises:
        ValueError: If the exposure concentration is negative or the IUR is negative or not finite.
    """
    _finite_non_negative(exposure_concentration_ug_per_m3, "exposure_concentration_ug_per_m3")
    if not math.isfinite(iur_per_ug_per_m3):
        raise ValueError("iur_per_ug_per_m3 must be finite")
    return calculate_cancer_risk(exposure_concentration_ug_per_m3, iur_per_ug_per_m3)


def _band_dose(
    band: str,
    share: float,
    mg_per_m3: float,
    rates: Mapping[str, float],
    weights: Mapping[str, float],
    frequency: float,
    duration: float,
) -> float | None:
    if isinstance(share, bool) or not math.isfinite(share) or share < 0:
        raise ValueError(f"the share of age band {band!r} must be finite and >= 0")
    if share == 0:
        return None
    if band not in rates or band not in weights:
        raise ValueError(f"no inhalation rate or body weight for age band {band!r}")
    return float(
        average_daily_dose(
            mg_per_m3,
            rates[band],
            frequency,
            duration,
            weights[band],
            duration * _DAYS_PER_YEAR,
        ),
    )


def doses_by_age_band(
    concentration_ug_per_m3: float,
    age_shares_percent: Mapping[str, float],
    inhalation_rates_m3_per_day: Mapping[str, float],
    body_weights_kg: Mapping[str, float],
    exposure_frequency_days_per_year: float,
    exposure_duration_years: float,
) -> dict[str, float]:
    """Average daily dose of each age band present in the population.

    ADD = C x IR x EF x ED / (BW x AT) with AT = ED x 365 days (non-cancer averaging), for every
    band whose population share is above zero.

    Args:
        concentration_ug_per_m3: Exposure concentration, in micrograms per cubic meter (ug/m^3).
        age_shares_percent: Age band -> percent of the population (0 to 100).
        inhalation_rates_m3_per_day: Age band -> inhalation rate (m^3/day); > 0.
        body_weights_kg: Age band -> body weight (kg); > 0.
        exposure_frequency_days_per_year: Days exposed per year (days/yr), 0 to 365.
        exposure_duration_years: Years of exposure (yr); > 0.

    Returns:
        Age band -> dose in milligrams per kilogram per day (mg/(kg*day)); empty if no band has a
        share above zero.

    Raises:
        ValueError: If a band present in the shares lacks a rate or weight, or a value is
            impossible.
    """
    _finite_non_negative(concentration_ug_per_m3, "concentration_ug_per_m3")
    if not 0 <= exposure_frequency_days_per_year <= _DAYS_PER_YEAR:
        raise ValueError("exposure_frequency_days_per_year must be within 0 to 365")
    mg_per_m3 = concentration_ug_per_m3 / _UG_PER_MG
    doses = {
        band: _band_dose(
            band,
            share,
            mg_per_m3,
            inhalation_rates_m3_per_day,
            body_weights_kg,
            exposure_frequency_days_per_year,
            exposure_duration_years,
        )
        for band, share in age_shares_percent.items()
    }
    return {band: dose for band, dose in doses.items() if dose is not None}


def highest_dose_band(doses: Mapping[str, float]) -> tuple[str, float] | None:
    """Return the age band with the highest dose and that dose, or None when there is none."""
    if not doses:
        return None
    band = max(doses, key=lambda b: (doses[b], b))
    return band, doses[band]
