"""Typed loader for the ``[occupational]`` settings (worker vapor models and dosimetry)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from config.occupational_activities import Activity, load_activities, load_stage_activities
from config.parsing import read_toml, require_number, require_str, section, subtable

NAME = "occupational"


def _fraction(block: dict[str, object], key: str, name: str) -> float:
    """A number in (0, 1]."""
    value = require_number(block, key, minimum=1e-9, name=name)
    if value > 1.0:
        raise ValueError(f"{name}.{key} must be at most 1")
    return value


def _positive(block: dict[str, object], key: str, name: str) -> float:
    return require_number(block, key, minimum=1e-9, name=name)


@dataclass(frozen=True)
class Conditions:
    """Conditions of the vapor models.

    Attributes:
        temperature_k: Air temperature, K.
        pressure_atm: Air pressure, atm.
        molar_volume_l_per_mol: Molar volume of an ideal gas, L/mol.
        correction_factor: Vapor pressure correction factor X (fraction of the chemical in the
            material handled), unitless, in (0, 1].
    """

    temperature_k: float
    pressure_atm: float
    molar_volume_l_per_mol: float
    correction_factor: float


@dataclass(frozen=True)
class Volatility:
    """The vapor pressure range in which the vapor models are used.

    Attributes:
        low_torr: Vapor pressure below which no vapor estimate is made, torr.
        high_torr: Vapor pressure above which the models are outside their range, torr.
    """

    low_torr: float
    high_torr: float


@dataclass(frozen=True)
class Ventilation:
    """One indoor ventilation tier of the box model.

    Attributes:
        label: Name shown with the result.
        rate_ft3_per_min: Room ventilation rate, ft^3/min.
        mixing_factor: Mixing efficiency k, unitless, in (0, 1].
    """

    label: str
    rate_ft3_per_min: float
    mixing_factor: float


@dataclass(frozen=True)
class IndoorVentilation:
    """The indoor ventilation tiers.

    Attributes:
        baseline: The typical tier.
        worst_case: The worst-case (enclosed zone) tier.
    """

    baseline: Ventilation
    worst_case: Ventilation


@dataclass(frozen=True)
class OutdoorVentilation:
    """Outdoor ventilation of the box model: Q = coefficient x (60 x air speed / 5,280).

    Attributes:
        coefficient_ft3_per_min: Coefficient of the outdoor ventilation rate, ft^3/min.
        baseline_air_speed_ft_per_min: Average wind speed of the baseline, ft/min.
        default_air_speed_ft_per_min: Air speed of the worst case when the model has none, ft/min.
        baseline_mixing_factor: Mixing factor k of the baseline, unitless, in (0, 1].
        worst_case_mixing_factor: Mixing factor k of the worst case, unitless, in (0, 1].
    """

    coefficient_ft3_per_min: float
    baseline_air_speed_ft_per_min: float
    default_air_speed_ft_per_min: float
    baseline_mixing_factor: float
    worst_case_mixing_factor: float


@dataclass(frozen=True)
class RoomSettings:
    """A room of the two-zone model.

    Attributes:
        volume_m3: Room volume, m^3.
        air_exchange_per_h: Air changes per hour, 1/h.
    """

    volume_m3: float
    air_exchange_per_h: float


@dataclass(frozen=True)
class TwoZoneSettings:
    """The near-field/far-field model of indoor evaporation activities.

    Attributes:
        near_field_length_m: Near-field length, m.
        near_field_width_m: Near-field width, m.
        near_field_height_m: Near-field height, m.
        near_field_air_speed_m_per_h: Air speed through the near field, m/h.
        baseline: The typical (high-end ventilation) room.
        worst_case: The worst-case (low-end ventilation) room.
    """

    near_field_length_m: float
    near_field_width_m: float
    near_field_height_m: float
    near_field_air_speed_m_per_h: float
    baseline: RoomSettings
    worst_case: RoomSettings


@dataclass(frozen=True)
class OccupationalSettings:
    """Worker screening factors.

    Attributes:
        shift_inhalation_m3: Air a worker breathes in a shift, m^3/day.
        daily_inhalation_m3: Air breathed in 24 hours (the resident rate), m^3/day.
        worker_days_per_year: Most days a worker works in a year, days/yr.
        tenure_years: Years of work, yr.
        lifetime_years: Averaging time for cancer risk, yr.
        twa_hours: Length of the time-weighted-average day, h.
        conditions: Air conditions of the vapor models.
        volatility: Vapor pressure range of the vapor models.
        indoor: Indoor ventilation tiers.
        outdoor: Outdoor ventilation.
        two_zone: Two-zone model dimensions and rooms.
        activities: Worker activities by key (read-only).
        stage_activities: Activity keys of each life cycle stage (read-only).
    """

    shift_inhalation_m3: float
    daily_inhalation_m3: float
    worker_days_per_year: float
    tenure_years: float
    lifetime_years: float
    twa_hours: float
    conditions: Conditions
    volatility: Volatility
    indoor: IndoorVentilation
    outdoor: OutdoorVentilation
    two_zone: TwoZoneSettings
    activities: MappingProxyType[str, Activity]
    stage_activities: MappingProxyType[str, tuple[str, ...]]


def _conditions(table: dict[str, object]) -> Conditions:
    return Conditions(
        temperature_k=_positive(table, "temperature_k", NAME),
        pressure_atm=_positive(table, "pressure_atm", NAME),
        molar_volume_l_per_mol=_positive(table, "molar_volume_l_per_mol", NAME),
        correction_factor=_fraction(table, "correction_factor", NAME),
    )


def _volatility(table: dict[str, object]) -> Volatility:
    name = f"{NAME}.volatility"
    block = subtable(table, "volatility", NAME)
    low, high = _positive(block, "low_torr", name), _positive(block, "high_torr", name)
    if low >= high:
        raise ValueError(f"{name}.low_torr must be below high_torr")
    return Volatility(low, high)


def _tier(indoor: dict[str, object], key: str) -> Ventilation:
    name = f"{NAME}.ventilation.indoor.{key}"
    block = subtable(indoor, key, f"{NAME}.ventilation.indoor")
    return Ventilation(
        label=require_str(block, "label", name),
        rate_ft3_per_min=_positive(block, "rate_ft3_per_min", name),
        mixing_factor=_fraction(block, "mixing_factor", name),
    )


def _indoor(table: dict[str, object]) -> IndoorVentilation:
    indoor = subtable(subtable(table, "ventilation", NAME), "indoor", f"{NAME}.ventilation")
    return IndoorVentilation(_tier(indoor, "baseline"), _tier(indoor, "worst_case"))


def _outdoor(table: dict[str, object]) -> OutdoorVentilation:
    name = f"{NAME}.ventilation.outdoor"
    block = subtable(subtable(table, "ventilation", NAME), "outdoor", f"{NAME}.ventilation")
    return OutdoorVentilation(
        coefficient_ft3_per_min=_positive(block, "coefficient_ft3_per_min", name),
        baseline_air_speed_ft_per_min=_positive(block, "baseline_air_speed_ft_per_min", name),
        default_air_speed_ft_per_min=_positive(block, "default_air_speed_ft_per_min", name),
        baseline_mixing_factor=_fraction(block, "baseline_mixing_factor", name),
        worst_case_mixing_factor=_fraction(block, "worst_case_mixing_factor", name),
    )


def _room(zone: dict[str, object], key: str) -> RoomSettings:
    name = f"{NAME}.two_zone.{key}"
    block = subtable(zone, key, f"{NAME}.two_zone")
    return RoomSettings(
        volume_m3=_positive(block, "volume_m3", name),
        air_exchange_per_h=_positive(block, "air_exchange_per_h", name),
    )


def _two_zone(table: dict[str, object]) -> TwoZoneSettings:
    name = f"{NAME}.two_zone"
    zone = subtable(table, "two_zone", NAME)
    return TwoZoneSettings(
        near_field_length_m=_positive(zone, "near_field_length_m", name),
        near_field_width_m=_positive(zone, "near_field_width_m", name),
        near_field_height_m=_positive(zone, "near_field_height_m", name),
        near_field_air_speed_m_per_h=_positive(zone, "near_field_air_speed_m_per_h", name),
        baseline=_room(zone, "baseline"),
        worst_case=_room(zone, "worst_case"),
    )


def _check(table: dict[str, object]) -> None:
    if _positive(table, "shift_inhalation_m3", NAME) > _positive(
        table,
        "daily_inhalation_m3",
        NAME,
    ):
        raise ValueError(f"{NAME}.shift_inhalation_m3 must not exceed daily_inhalation_m3")
    if _positive(table, "worker_days_per_year", NAME) > 365.0:
        raise ValueError(f"{NAME}.worker_days_per_year must be at most 365")
    if _positive(table, "twa_hours", NAME) > 24.0:
        raise ValueError(f"{NAME}.twa_hours must be at most 24")
    if _positive(table, "tenure_years", NAME) > _positive(table, "lifetime_years", NAME):
        raise ValueError(f"{NAME}.tenure_years must not exceed lifetime_years")


def load_occupational_settings(path: Path | None = None) -> OccupationalSettings:
    """Load and validate the occupational settings.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key (and, for an
            activity, the activity).
    """
    table = section(read_toml(path), NAME)
    _check(table)
    activities = load_activities(table)
    return OccupationalSettings(
        shift_inhalation_m3=_positive(table, "shift_inhalation_m3", NAME),
        daily_inhalation_m3=_positive(table, "daily_inhalation_m3", NAME),
        worker_days_per_year=_positive(table, "worker_days_per_year", NAME),
        tenure_years=_positive(table, "tenure_years", NAME),
        lifetime_years=_positive(table, "lifetime_years", NAME),
        twa_hours=_positive(table, "twa_hours", NAME),
        conditions=_conditions(table),
        volatility=_volatility(table),
        indoor=_indoor(table),
        outdoor=_outdoor(table),
        two_zone=_two_zone(table),
        activities=activities,
        stage_activities=load_stage_activities(table, activities),
    )


@lru_cache(maxsize=1)
def get_occupational_settings() -> OccupationalSettings:
    """Return the cached occupational settings from the default file."""
    return load_occupational_settings()
