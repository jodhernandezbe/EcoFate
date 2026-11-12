"""The activities of a facility, modelled with the chemical's molecular weight and vapor pressure.

Nothing is defaulted: a missing or unusable property means no activity is modelled, with a warning
naming it. Below ChemSTEER's preferred vapor pressure range no vapor estimate is made.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from commons.units import convert
from config.occupational import OccupationalSettings
from tools.assessment.helpers.activities.evaluate import (
    ActivityResult,
    CaseResult,
    Chemical,
    Context,
    evaluate,
    volatility,
)
from tools.assessment.helpers.activities.select import Selection
from tools.assessment.helpers.occupational.workplace import Sources, Workplace
from tools.schemas import ActivityCase, DrivingActivity, Volatility, WorkerActivity

BELOW_RANGE = (
    "the vapor pressure ({vp:g} torr) is below {low:g} torr, the range of the vapor models, so "
    "the chemical is too little volatile for a vapor model; particulate (dust) exposure is not "
    "modelled"
)


@dataclass(frozen=True)
class Modelled:
    """The activities modelled for a facility.

    Attributes:
        results: The activities, highest worst-case 8-hour average first.
        reason: Why none was modelled, or None.
        warnings: Notes on the properties and on activities that could not be computed.
    """

    results: tuple[ActivityResult, ...]
    reason: str | None
    warnings: tuple[str, ...]


def _usable(value: float | None) -> float | None:
    if value is None or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def missing_properties(workplace: Workplace) -> list[str]:
    """The names of the properties the models need that are missing or unusable."""
    wanted = (
        ("molecular weight", workplace.molecular_weight),
        ("vapor pressure", workplace.vapor_pressure_mmhg),
    )
    return [name for name, value in wanted if _usable(value) is None]


def chemical_of(workplace: Workplace) -> Chemical | None:
    """The pure chemical (g/mol, torr), or None when a property is missing."""
    weight, pressure = _usable(workplace.molecular_weight), _usable(workplace.vapor_pressure_mmhg)
    if weight is None or pressure is None:
        return None
    return Chemical(weight, convert(pressure, "mmHg", "torr"))


def case_view(result: CaseResult) -> ActivityCase:
    return ActivityCase(
        estimator=result.estimator,
        airflow_m3_per_s=result.airflow_m3_per_s,
        mixing_factor=result.mixing_factor,
        room_m3=result.room_m3,
        air_exchange_per_h=result.air_exchange_per_h,
        generation_g_per_s=result.generation_g_per_s,
        concentration_mg_m3=result.concentration_mg_m3,
        capped=result.capped,
        twa_mg_m3=result.twa_mg_m3,
    )


def activity_view(result: ActivityResult) -> WorkerActivity:
    """One evaluated activity as the result carries it."""
    return WorkerActivity(
        key=result.key,
        label=result.label,
        model=result.model,
        setting=result.setting,
        hours=result.hours,
        typical=case_view(result.typical),
        worst_case=case_view(result.worst_case),
        warnings=list(result.warnings),
        statement=result.statement,
    )


def driving_view(result: ActivityResult) -> DrivingActivity:
    """The driving activity as the result carries it."""
    return DrivingActivity(
        key=result.key,
        label=result.label,
        model=result.model,
        setting=result.setting,
        hours=result.hours,
        estimator=result.worst_case.estimator,
        statement=result.statement,
    )


def _evaluated(keys: tuple[str, ...], ctx: Context) -> tuple[list[ActivityResult], list[str]]:
    found: list[ActivityResult] = []
    notes: list[str] = []
    for key in keys:
        try:
            result = evaluate(ctx.settings.activities[key], ctx)
        except ValueError as error:
            notes.append(f"{key} was not modelled: {error}")
        else:
            if result is not None:
                found.append(result)
    return found, notes


def _warnings(results: list[ActivityResult], notes: list[str]) -> tuple[str, ...]:
    from_activities = (f"{r.label}: {w}" for r in results for w in r.warnings)
    return (*notes, *dict.fromkeys(from_activities))


def _no_properties(missing: list[str]) -> Modelled:
    names = " and ".join(missing)
    reason = f"the chemical's {names} {'is' if len(missing) == 1 else 'are'} missing"
    return Modelled((), reason, ())


def model_activities(selection: Selection, workplace: Workplace, sources: Sources) -> Modelled:
    """Both outputs of every selected activity, ordered by worst-case 8-hour average."""
    if not selection.activities:
        return Modelled((), selection.reason, ())
    chemical = chemical_of(workplace)
    if chemical is None:
        return _no_properties(missing_properties(workplace))
    s = workplace.settings
    level = volatility(chemical.vapor_pressure_torr, s)
    if level == "below":
        reason = BELOW_RANGE.format(vp=chemical.vapor_pressure_torr, low=s.volatility.low_torr)
        return Modelled((), reason, ())
    return _modelled(selection, Context(chemical, s, sources.tra_table, sources.tra_settings))


def _modelled(selection: Selection, ctx: Context) -> Modelled:
    found, notes = _evaluated(selection.activities, ctx)
    ranked = sorted(found, key=lambda r: r.worst_case.twa_mg_m3, reverse=True)
    reason = None if ranked else "no activity could be computed"
    return Modelled(tuple(ranked), reason, _warnings(ranked, notes))


def level_of(workplace: Workplace, settings: OccupationalSettings) -> Volatility | None:
    """Where the vapor pressure falls against the preferred range; None without a usable one."""
    pressure = _usable(workplace.vapor_pressure_mmhg)
    return None if pressure is None else volatility(convert(pressure, "mmHg", "torr"), settings)
