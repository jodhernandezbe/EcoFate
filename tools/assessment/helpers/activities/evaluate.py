"""The typical and worst-case workplace air of one worker activity (EPA ChemSTEER, ECETOC TRA).

The vapor generation rate comes from the activity's ChemSTEER model. An indoor evaporation
activity (penetration or mass transfer model) is breathed in the near field of the two-zone
model; every other activity is a well-mixed mass balance with ChemSTEER's indoor or outdoor
ventilation. Above ChemSTEER's preferred vapor pressure range an evaporation activity takes the
ECETOC TRA tier-1 estimate when one exists, else the model value with a warning. Every
concentration is capped at the chemical's saturation concentration. Below the range nothing is
computed. Nothing here is defaulted: a missing property is the caller's reason to skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from commons.units import convert
from config.ecetoc_tra import EcetocTraSettings
from config.occupational import OccupationalSettings
from config.occupational_activities import Activity, AirSpeedParameters, Ap42Parameters
from models.exposure import occupational as balance
from models.exposure import vapor_generation as vg
from models.exposure.two_zone import NearField, Room, two_zone_averages
from tools.assessment.helpers.occupational_bands.ecetoc import TraTable, estimate

Volatility = Literal["below", "within", "above"]
Estimator = Literal["mass_balance", "two_zone", "ecetoc_tra"]
Case = Literal["typical", "worst_case"]
CASES: tuple[Case, Case] = ("typical", "worst_case")
EVAPORATION = ("penetration", "mass_transfer")
OUT_OF_RANGE = (
    "the vapor pressure is above the range in which ChemSTEER's evaporation models were "
    "validated, so this value likely overestimates"
)


@dataclass(frozen=True)
class Chemical:
    """The pure chemical: molecular weight (g/mol) and vapor pressure (torr) at about 25 degC."""

    molecular_weight: float
    vapor_pressure_torr: float


@dataclass(frozen=True)
class Context:
    """Everything an activity is evaluated with, beyond the activity itself."""

    chemical: Chemical
    settings: OccupationalSettings
    tra_table: TraTable
    tra_settings: EcetocTraSettings


@dataclass(frozen=True)
class CaseResult:
    """One output of an activity (typical or worst case).

    Attributes:
        estimator: "mass_balance", "two_zone" or "ecetoc_tra".
        airflow_m3_per_s: Ventilation Q of the mass balance, m^3/s; None otherwise.
        mixing_factor: k of the mass balance, unitless; None otherwise.
        room_m3: Far-field volume of the two-zone model, m^3; None otherwise.
        air_exchange_per_h: Far-field air changes, 1/h; None otherwise.
        generation_g_per_s: Vapor generation rate G, g/s; None for the band estimate.
        concentration_mg_m3: Air the worker breathes during the activity, mg/m^3; None for the
            band estimate (an 8-hour value only).
        capped: Whether the saturation concentration set the value.
        twa_mg_m3: 8-hour time-weighted average, mg/m^3.
    """

    estimator: Estimator
    airflow_m3_per_s: float | None
    mixing_factor: float | None
    room_m3: float | None
    air_exchange_per_h: float | None
    generation_g_per_s: float | None
    concentration_mg_m3: float | None
    capped: bool
    twa_mg_m3: float


@dataclass(frozen=True)
class ActivityResult:
    """Both outputs of one activity, the warnings and the band estimate's statement."""

    key: str
    label: str
    model: str
    setting: str
    hours: float
    typical: CaseResult
    worst_case: CaseResult
    warnings: tuple[str, ...]
    statement: str | None


def volatility(vapor_pressure_torr: float, settings: OccupationalSettings) -> Volatility:
    """Where the vapor pressure (torr) falls against ChemSTEER's preferred range."""
    if vapor_pressure_torr < settings.volatility.low_torr:
        return "below"
    return "above" if vapor_pressure_torr > settings.volatility.high_torr else "within"


def saturation_mg_m3(chemical: Chemical, settings: OccupationalSettings) -> float:
    """Saturation concentration of the pure chemical, mg/m^3."""
    c = settings.conditions
    return vg.saturation_concentration(
        chemical.molecular_weight,
        chemical.vapor_pressure_torr,
        c.molar_volume_l_per_mol,
        c.correction_factor,
    )


def _pick(case: Case, typical: float, worst: float) -> float:
    return typical if case == "typical" else worst


def generation_g_per_s(activity: Activity, case: Case, ctx: Context) -> float:
    """Vapor generation rate of the activity's model for one output, g/s."""
    p, chem, c = activity.parameters, ctx.chemical, ctx.settings.conditions
    mw, vp, t, x = (
        chem.molecular_weight,
        chem.vapor_pressure_torr,
        c.temperature_k,
        c.correction_factor,
    )
    if isinstance(p, Ap42Parameters):
        f = _pick(case, p.saturation_factor.typical, p.saturation_factor.worst_case)
        return vg.loading_rate(f, mw, p.container_gallons, p.fill_rate_per_hour, vp, t, x)
    d = _pick(case, p.diameter_cm.typical, p.diameter_cm.worst_case)
    if activity.model == "penetration":
        return vg.penetration_rate(mw, vp, p.air_speed_ft_per_min, d, t, c.pressure_atm, x)
    return vg.mass_transfer_rate(mw, vp, p.air_speed_ft_per_min, d, t, x)


def _ventilation(activity: Activity, case: Case, s: OccupationalSettings) -> tuple[float, float]:
    """Q (ft^3/min) and k of the mass balance (ChemSTEER Table B-2a)."""
    if activity.setting == "indoor":
        tier = s.indoor.baseline if case == "typical" else s.indoor.worst_case
        return tier.rate_ft3_per_min, tier.mixing_factor
    o = s.outdoor
    own = activity.parameters
    worst_speed = (
        own.air_speed_ft_per_min
        if isinstance(own, AirSpeedParameters)
        else o.default_air_speed_ft_per_min
    )
    speed = _pick(case, o.baseline_air_speed_ft_per_min, worst_speed)
    k = _pick(case, o.baseline_mixing_factor, o.worst_case_mixing_factor)
    return balance.outdoor_ventilation_ft3_per_min(o.coefficient_ft3_per_min, speed), k


def _twa(concentration: float, activity: Activity, ctx: Context) -> float:
    """The 8-hour average of a concentration (mg/m^3) held for the activity's hours."""
    return balance.twa_concentration(concentration, activity.hours, ctx.settings.twa_hours)


def _mass_balance(activity: Activity, case: Case, ctx: Context, saturation: float) -> CaseResult:
    g = generation_g_per_s(activity, case, ctx)
    rate_cfm, k = _ventilation(activity, case, ctx.settings)
    q = convert(rate_cfm, "ft^3/min", "m^3/s")
    air = balance.workplace_concentration(g * 1000.0, q, k, saturation)
    conc = air.concentration_mg_per_m3
    twa = _twa(conc, activity, ctx)
    return CaseResult("mass_balance", q, k, None, None, g, conc, air.capped, twa)


def _near_zone(ctx: Context) -> NearField:
    """The near-field box around the worker, from the two-zone settings."""
    z = ctx.settings.two_zone
    return NearField(
        z.near_field_length_m,
        z.near_field_width_m,
        z.near_field_height_m,
        z.near_field_air_speed_m_per_h,
    )


def _near_field(activity: Activity, case: Case, ctx: Context, saturation: float) -> CaseResult:
    z = ctx.settings.two_zone
    room = z.baseline if case == "typical" else z.worst_case
    g = generation_g_per_s(activity, case, ctx)
    whole = Room(room.volume_m3, room.air_exchange_per_h)
    average = two_zone_averages(g, activity.hours, _near_zone(ctx), whole).near_field_mg_per_m3
    air = min(average, saturation)
    volume, exchange = room.volume_m3, room.air_exchange_per_h
    twa = _twa(air, activity, ctx)
    return CaseResult("two_zone", None, None, volume, exchange, g, air, average > saturation, twa)


def _modelled(activity: Activity, case: Case, ctx: Context, saturation: float) -> CaseResult:
    if activity.setting == "indoor" and activity.model in EVAPORATION:
        return _near_field(activity, case, ctx, saturation)
    return _mass_balance(activity, case, ctx, saturation)


def _band(twa: float, saturation: float) -> CaseResult:
    capped = twa > saturation
    return CaseResult(
        "ecetoc_tra",
        None,
        None,
        None,
        None,
        None,
        None,
        capped,
        min(twa, saturation),
    )


def evaluate(activity: Activity, ctx: Context) -> ActivityResult | None:
    """Both outputs of ``activity``; None below ChemSTEER's volatility range (nothing to model).

    Raises:
        ValueError: If a property or setting is out of the models' range.
    """
    level = volatility(ctx.chemical.vapor_pressure_torr, ctx.settings)
    if level == "below":
        return None
    saturation = saturation_mg_m3(ctx.chemical, ctx.settings)
    if level == "above" and activity.model in EVAPORATION:
        return _above_range(activity, ctx, saturation)
    typical, worst = (_modelled(activity, case, ctx, saturation) for case in CASES)
    return _result(activity, typical, worst, (), None)


def _above_range(activity: Activity, ctx: Context, saturation: float) -> ActivityResult:
    pa = convert(ctx.chemical.vapor_pressure_torr, "torr", "Pa")
    tra = estimate(
        activity.proc,
        pa,
        ctx.chemical.molecular_weight,
        activity.hours,
        ctx.settings.conditions.molar_volume_l_per_mol,
        ctx.tra_table,
        ctx.tra_settings,
    )
    if tra.baseline_mg_m3 is None or tra.worst_case_mg_m3 is None:
        typical, worst = (_modelled(activity, case, ctx, saturation) for case in CASES)
        return _result(activity, typical, worst, (OUT_OF_RANGE,), None)
    typical, worst = _band(tra.baseline_mg_m3, saturation), _band(tra.worst_case_mg_m3, saturation)
    return _result(activity, typical, worst, (), tra.statement)


def _result(
    activity: Activity,
    typical: CaseResult,
    worst: CaseResult,
    warnings: tuple[str, ...],
    statement: str | None,
) -> ActivityResult:
    return ActivityResult(
        key=activity.key,
        label=activity.label,
        model=activity.model,
        setting=activity.setting,
        hours=activity.hours,
        typical=typical,
        worst_case=worst,
        warnings=warnings,
        statement=statement,
    )
