"""Typed loader for the ``[scenario]`` settings (worst-case scenarios of exposure pathways)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from config.parsing import (
    read_toml,
    require_fraction,
    require_int,
    require_str,
    section,
    subtable,
)

NAME = "scenario"
FactorGroup = Literal["source", "release", "conditions", "receptor_model"]
GROUPS: tuple[FactorGroup, ...] = ("source", "release", "conditions", "receptor_model")
_BY_NAME: dict[str, FactorGroup] = {group: group for group in GROUPS}


@dataclass(frozen=True)
class FactorSpec:
    """How a factor of a scenario is shown.

    Attributes:
        group: The group it belongs to (source, release, conditions, receptor_model).
        label: Name shown with the value.
        unit: Unit of the value; empty when unitless or when the value carries its own.
    """

    group: FactorGroup
    label: str
    unit: str


@dataclass(frozen=True)
class ScenarioSettings:
    """Worst-case scenario settings.

    Attributes:
        receptor_fraction: A receptor is most affected at this fraction of the maximum or more,
            in (0, 1].
        max_receptors: Most receptors listed per scenario.
        pathways: Pathway key -> name (medium, route, receptor class).
        quantities: Quantity key -> name.
        factors: Factor key -> how it is shown.
    """

    receptor_fraction: float
    max_receptors: int
    pathways: Mapping[str, str]
    quantities: Mapping[str, str]
    factors: Mapping[str, FactorSpec]


def _texts(table: dict[str, object], key: str) -> Mapping[str, str]:
    block = subtable(table, key, NAME)
    texts = {name: require_str(block, name, f"{NAME}.{key}").strip() for name in block}
    return MappingProxyType(texts)


def _factor(key: str, block: dict[str, object]) -> FactorSpec:
    name = f"{NAME}.factors.{key}"
    raw = require_str(block, "group", name)
    group = _BY_NAME.get(raw)
    if group is None:
        raise ValueError(f"{name}.group must be one of {', '.join(GROUPS)}")
    unit = block.get("unit")
    if not isinstance(unit, str):
        raise ValueError(f"{name}.unit must be a string (empty when unitless)")
    return FactorSpec(group, require_str(block, "label", name).strip(), unit)


def _factors(table: dict[str, object]) -> Mapping[str, FactorSpec]:
    block = subtable(table, "factors", NAME)
    return MappingProxyType(
        {key: _factor(key, subtable(block, key, f"{NAME}.factors")) for key in block},
    )


def load_scenario_settings(path: Path | None = None) -> ScenarioSettings:
    """Load and validate the scenario settings.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), NAME)
    fraction = require_fraction(table, "receptor_fraction", NAME)
    if fraction == 0.0:
        raise ValueError(f"{NAME}.receptor_fraction must be above 0")
    return ScenarioSettings(
        receptor_fraction=fraction,
        max_receptors=require_int(table, "max_receptors", minimum=1, name=NAME),
        pathways=_texts(table, "pathways"),
        quantities=_texts(table, "quantities"),
        factors=_factors(table),
    )


@lru_cache(maxsize=1)
def get_scenario_settings() -> ScenarioSettings:
    """Return the cached scenario settings from the default file."""
    return load_scenario_settings()
