"""The limit ratio, worker hazard quotient, cancer risk and band of one 8-hour average.

RAGS Part F style chronic dosimetry of a worker: the 8-hour average is breathed for the shift
volume on the days worked in a year (at most the plant's operating days), over the tenure (hazard
quotient) or the lifetime (cancer risk). A missing input gives None, never zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from commons.bands import Band, highest_band
from config.occupational import OccupationalSettings
from config.risk_bands import get_risk_bands
from models.exposure import occupational as model
from tools.schemas import ActivityCase, CaseEstimator, WorkerCase


@dataclass(frozen=True)
class Benchmarks:
    """The values an 8-hour average is compared with (None = not available).

    Attributes:
        oel: 8-hour occupational exposure limit, mg/m^3.
        rfc: Inhalation reference concentration, mg/m^3.
        iur: Inhalation unit risk, (ug/m^3)^-1.
        days: Days a year the plant operates, d/yr.
    """

    oel: float | None
    rfc: float | None
    iur: float | None
    days: float | None


def empty_case() -> WorkerCase:
    """A case with nothing computed."""
    return WorkerCase(
        setting=None,
        estimator=None,
        airflow_m3_per_s=None,
        mixing_factor=None,
        room_m3=None,
        air_exchange_per_h=None,
        generation_g_per_s=None,
        workplace_concentration_mg_m3=None,
        capped=None,
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


def _hazards(
    twa: float,
    b: Benchmarks,
    s: OccupationalSettings,
) -> tuple[float | None, float | None]:
    """Worker hazard quotient and cancer risk; None without the benchmark or the schedule."""
    if b.days is None:
        return None, None
    adc, ladc = _chronic(twa, b.days, s.tenure_years, s), _chronic(twa, b.days, s.lifetime_years, s)
    hq = None if b.rfc is None else model.worker_hazard_quotient(adc, b.rfc)
    risk = None if b.iur is None else model.worker_cancer_risk(ladc, b.iur)
    return hq, risk


def band_of(ratio: float | None, hq: float | None, risk: float | None) -> Band | None:
    """The highest band of the three quantities; None when none could be computed."""
    b = get_risk_bands()
    return highest_band(
        [
            (ratio, b.oel_ratio_lower, b.oel_ratio_upper),
            (hq, b.hq_lower, b.hq_upper),
            (risk, b.cancer_risk_lower, b.cancer_risk_upper),
        ],
    )


def with_risks(case: WorkerCase, b: Benchmarks, s: OccupationalSettings) -> WorkerCase:
    """``case`` with its limit ratio, hazard quotient, cancer risk and band from its 8-hour TWA."""
    twa = case["twa_mg_m3"]
    if twa is None:
        return case
    ratio = None if b.oel is None else model.oel_ratio(twa, b.oel)
    hq, risk = _hazards(twa, b, s)
    return {
        **case,
        "oel_ratio": ratio,
        "hq": hq,
        "cancer_risk": risk,
        "risk_tier": band_of(ratio, hq, risk),
    }


def activity_case(
    setting: str,
    values: ActivityCase,
    b: Benchmarks,
    s: OccupationalSettings,
) -> WorkerCase:
    """The case of a modelled activity output."""
    case = empty_case()
    case.update(
        setting=setting,
        estimator=values["estimator"],
        airflow_m3_per_s=values["airflow_m3_per_s"],
        mixing_factor=values["mixing_factor"],
        room_m3=values["room_m3"],
        air_exchange_per_h=values["air_exchange_per_h"],
        generation_g_per_s=values["generation_g_per_s"],
        workplace_concentration_mg_m3=values["concentration_mg_m3"],
        capped=values["capped"],
        twa_mg_m3=values["twa_mg_m3"],
    )
    return with_risks(case, b, s)


def measured_case(twa: float | None, b: Benchmarks, s: OccupationalSettings) -> WorkerCase:
    """The case of a measured 8-hour average (None = below detection)."""
    estimator: CaseEstimator = "monitoring"
    case = empty_case()
    case.update(estimator=estimator, twa_mg_m3=twa)
    return with_risks(case, b, s)
