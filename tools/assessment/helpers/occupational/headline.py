"""The headline baseline and worst case: measured data first, else the driving activity."""

from __future__ import annotations

from dataclasses import dataclass

from commons.bands import Band
from config.occupational import OccupationalSettings
from tools.assessment.helpers.monitoring.cehd import MonitoringResult
from tools.assessment.helpers.occupational.dosimetry import (
    Benchmarks,
    activity_case,
    empty_case,
    measured_case,
)
from tools.assessment.helpers.occupational.modelled import Modelled, case_view
from tools.schemas import Evidence, WorkerCase

BELOW_DETECTION = (
    "the measured median is below detection, so the baseline is not computed and the band is "
    "that of the worst case (the 95th percentile)"
)


@dataclass(frozen=True)
class Headline:
    """What the result rests on.

    Attributes:
        evidence: "monitoring", "activity_model" or None.
        baseline: The baseline case.
        worst_case: The worst case.
        tier: The result's band: the baseline band, or the worst-case one when the baseline is null.
        warnings: Notes on the choice.
    """

    evidence: Evidence | None
    baseline: WorkerCase
    worst_case: WorkerCase
    tier: Band | None
    warnings: tuple[str, ...]


def _tier(baseline: WorkerCase, worst: WorkerCase) -> tuple[Band | None, tuple[str, ...]]:
    if baseline["twa_mg_m3"] is None and worst["twa_mg_m3"] is not None:
        return worst["risk_tier"], (BELOW_DETECTION,)
    return baseline["risk_tier"], ()


def _measured(found: MonitoringResult, b: Benchmarks, s: OccupationalSettings) -> Headline:
    baseline = measured_case(found.median_mg_m3, b, s)
    worst = measured_case(found.p95_mg_m3, b, s)
    tier, notes = _tier(baseline, worst)
    return Headline("monitoring", baseline, worst, tier, notes)


def _modelled(modelled: Modelled, b: Benchmarks, s: OccupationalSettings) -> Headline:
    driving = modelled.results[0]
    typical = activity_case(driving.setting, case_view(driving.typical), b, s)
    worst = activity_case(driving.setting, case_view(driving.worst_case), b, s)
    return Headline("activity_model", typical, worst, typical["risk_tier"], ())


def headline(
    modelled: Modelled,
    found: MonitoringResult,
    b: Benchmarks,
    s: OccupationalSettings,
) -> Headline:
    """Measured values when OSHA's data have them, else the driving activity, else nothing."""
    if found.available:
        return _measured(found, b, s)
    if modelled.results:
        return _modelled(modelled, b, s)
    return Headline(None, empty_case(), empty_case(), None, ())
