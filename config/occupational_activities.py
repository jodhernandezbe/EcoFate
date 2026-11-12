"""Typed loader for the worker activities of ``[occupational]``.

An activity names the model that estimates its vapor generation and the parameters that model
needs; a parameter the model does not use is ignored, one it needs and lacks is an error that
names the activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

from config.parsing import (
    as_table,
    names,
    require_number,
    require_pair,
    require_str,
    subtable,
)

NAME = "occupational"
MODELS = ("ap42_loading", "penetration", "mass_transfer")
SETTINGS = ("indoor", "outdoor")
STAGES = ("Manufacturing", "Processing", "Industrial use")
PENETRATION_MAX_AIR_SPEED_FT_PER_MIN = 100.0

ModelName = Literal["ap42_loading", "penetration", "mass_transfer"]
SettingName = Literal["indoor", "outdoor"]


@dataclass(frozen=True)
class Pair:
    """A value for the typical and the worst case.

    Attributes:
        typical: Value of the typical (baseline) case.
        worst_case: Value of the worst case.
    """

    typical: float
    worst_case: float


@dataclass(frozen=True)
class Ap42Parameters:
    """Parameters of the AP-42 loading model.

    Attributes:
        container_gallons: Volume of the container loaded, gal.
        fill_rate_per_hour: Containers filled per hour, 1/h.
        saturation_factor: Saturation factor S of AP-42 loading, unitless, in (0, 1].
    """

    container_gallons: float
    fill_rate_per_hour: float
    saturation_factor: Pair


@dataclass(frozen=True)
class AirSpeedParameters:
    """Parameters of the penetration and mass transfer models.

    Attributes:
        air_speed_ft_per_min: Air speed over the liquid surface, ft/min.
        diameter_cm: Diameter of the evaporating surface, cm.
    """

    air_speed_ft_per_min: float
    diameter_cm: Pair


@dataclass(frozen=True)
class Activity:
    """One worker activity.

    Attributes:
        key: Its key in the configuration.
        label: Name shown with the result.
        model: The model that estimates its vapor generation.
        setting: Where it takes place.
        hours: Hours per day the worker performs it, h/day, in (0, 24].
        parameters: The parameters of its model.
        proc: ECETOC TRA process category, or None when none describes the activity.
    """

    key: str
    label: str
    model: ModelName
    setting: SettingName
    hours: float
    parameters: Ap42Parameters | AirSpeedParameters
    proc: str | None


def _ap42(block: dict[str, object], name: str) -> Ap42Parameters:
    typical, worst = require_pair(block, "saturation_factor", minimum=1e-9, name=name)
    if max(typical, worst) > 1.0 or worst < typical:
        raise ValueError(f"{name}.saturation_factor must be in (0, 1] with worst case >= typical")
    return Ap42Parameters(
        container_gallons=require_number(block, "container_gallons", minimum=1e-9, name=name),
        fill_rate_per_hour=require_number(block, "fill_rate_per_hour", minimum=1e-9, name=name),
        saturation_factor=Pair(typical, worst),
    )


def _air_speed(block: dict[str, object], name: str, model: str) -> AirSpeedParameters:
    speed = require_number(block, "air_speed_ft_per_min", minimum=1e-9, name=name)
    limit = PENETRATION_MAX_AIR_SPEED_FT_PER_MIN
    if (model == "penetration") != (speed <= limit):
        side = "at most" if model == "penetration" else "above"
        raise ValueError(f"{name}.air_speed_ft_per_min must be {side} {limit:g} for {model}")
    typical, worst = require_pair(block, "diameter_cm", minimum=1e-9, name=name)
    if worst < typical:
        raise ValueError(f"{name}.diameter_cm worst case must be >= typical")
    return AirSpeedParameters(speed, Pair(typical, worst))


def _choice(block: dict[str, object], key: str, allowed: tuple[str, ...], name: str) -> str:
    value = require_str(block, key, name)
    if value not in allowed:
        raise ValueError(f"{name}.{key} must be one of {', '.join(allowed)}, got {value!r}")
    return value


def _proc(block: dict[str, object], name: str) -> str | None:
    return require_str(block, "proc", name).strip() if "proc" in block else None


def _hours(block: dict[str, object], name: str) -> float:
    hours = require_number(block, "hours", minimum=1e-9, name=name)
    if hours > 24.0:
        raise ValueError(f"{name}.hours must be at most 24")
    return hours


def _activity(key: str, block: dict[str, object]) -> Activity:
    name = f"{NAME}.activities.{key}"
    model = _choice(block, "model", MODELS, name)
    parameters = _ap42(block, name) if model == "ap42_loading" else _air_speed(block, name, model)
    return Activity(
        key=key,
        label=require_str(block, "label", name),
        model=cast(ModelName, model),
        setting=cast(SettingName, _choice(block, "setting", SETTINGS, name)),
        hours=_hours(block, name),
        parameters=parameters,
        proc=_proc(block, name),
    )


def load_activities(table: dict[str, object]) -> MappingProxyType[str, Activity]:
    """The activities of the ``[occupational]`` table, by key (read-only)."""
    raw = subtable(table, "activities", NAME)
    if not raw:
        raise ValueError(f"{NAME}.activities must not be empty")
    return MappingProxyType(
        {
            key: _activity(key, as_table(block, f"{NAME}.activities.{key}"))
            for key, block in raw.items()
        },
    )


def load_stage_activities(
    table: dict[str, object],
    activities: MappingProxyType[str, Activity],
) -> MappingProxyType[str, tuple[str, ...]]:
    """The activity keys of each life cycle stage; every key must name a configured activity."""
    raw = subtable(table, "stage_activities", NAME)
    name = f"{NAME}.stage_activities"
    stages: dict[str, tuple[str, ...]] = {}
    for stage in raw:
        if stage not in STAGES:
            raise ValueError(f"{name}.{stage} is not a life cycle stage ({', '.join(STAGES)})")
        keys = names(raw, stage, name, allow_empty=False)
        unknown = [key for key in keys if key not in activities]
        if unknown:
            raise ValueError(f"{name}.{stage} names unknown activity {unknown[0]!r}")
        stages[stage] = keys
    return MappingProxyType(stages)
