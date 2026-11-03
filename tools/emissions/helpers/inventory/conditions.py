"""TSCA conditions of use and life cycle stages of a facility, from its TRI activities.

A TRI submission says which Section 3 activities the facility does with the chemical (produce,
import, process as a reactant, ...). The EPA crosswalk maps each activity to a TSCA life cycle
stage and condition-of-use category. Only the crosswalk rows of the configured level without a
TRI sub-use code are used, joined on the Form R section ("3.2b"). Nothing is guessed: an
activity the crosswalk lacks is dropped with a warning, and an empty result says why.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from config.conditions_of_use import ConditionsSettings
from tools.schemas import ConditionOfUse

logger = logging.getLogger(__name__)

NOT_REQUESTED = "conditions of use were not requested"
NO_ACTIVITY_DATA = "TRI did not return activity data for this submission"
NO_ACTIVITY = "TRI reported no activity for this submission"
NO_ROWS = "the reported activities have no row in the TSCA crosswalk"


@dataclass(frozen=True)
class Conditions:
    """A facility's conditions of use, their distinct life cycle stages, and why none."""

    conditions_of_use: list[ConditionOfUse]
    lifecycle_stages: list[str]
    note: str | None


ConditionsFor = Callable[[frozenset[str], bool], Conditions]
"""Conditions from a facility's activity sections and whether TRI returned activity data."""


def not_requested() -> Conditions:
    """The result when no mapper is given."""
    return Conditions([], [], NOT_REQUESTED)


@dataclass(frozen=True)
class Crosswalk:
    """Form R section -> its conditions, in crosswalk order; empty with a reason if unusable."""

    by_section: MappingProxyType[str, tuple[ConditionOfUse, ...]]
    unavailable: str | None
    warnings: tuple[str, ...]


def _unavailable(reason: str) -> Crosswalk:
    return Crosswalk(MappingProxyType({}), reason, (reason,))


def _field(row: dict[str, str], column: str) -> str:
    return " ".join((row.get(column) or "").split())


def _condition(row: dict[str, str], settings: ConditionsSettings) -> ConditionOfUse | None:
    """The row's condition, or None when it is not a usable level row of a known section."""
    if _field(row, settings.level_column) != settings.level or _field(row, settings.subuse_column):
        return None
    found = settings.section_pattern.search(_field(row, settings.section_column))
    stage, category = _field(row, settings.stage_column), _field(row, settings.category_column)
    if found is None or not stage or not category:
        return None
    return ConditionOfUse(
        tri_activity=_field(row, settings.activity_column),
        tri_section=found.group("section"),
        lifecycle_stage=stage,
        cou_category=category,
        mapping_strength=_field(row, settings.strength_column),
    )


def _columns(settings: ConditionsSettings) -> tuple[str, ...]:
    return (
        settings.level_column,
        settings.section_column,
        settings.subuse_column,
        settings.stage_column,
        settings.category_column,
        settings.strength_column,
        settings.activity_column,
    )


def _read(settings: ConditionsSettings) -> Crosswalk:
    with settings.crosswalk_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in _columns(settings) if c not in (reader.fieldnames or [])]
        if missing:
            return _unavailable(f"{settings.crosswalk_path.name}: missing column {missing[0]}")
        grouped: dict[str, list[ConditionOfUse]] = {}
        for row in reader:
            condition = _condition(row, settings)
            if condition is not None and condition not in grouped.get(condition["tri_section"], []):
                grouped.setdefault(condition["tri_section"], []).append(condition)
    return Crosswalk(MappingProxyType({k: tuple(v) for k, v in grouped.items()}), None, ())


def load_crosswalk(settings: ConditionsSettings) -> Crosswalk:
    """Read the crosswalk; a missing or malformed file gives an unavailable crosswalk."""
    try:
        return _read(settings)
    except (OSError, csv.Error, UnicodeDecodeError) as error:
        return _unavailable(f"{settings.crosswalk_path.name} cannot be read: {error}")


@lru_cache(maxsize=4)
def get_crosswalk(settings: ConditionsSettings) -> Crosswalk:
    """The crosswalk for ``settings``, read once per process; problems are logged once."""
    crosswalk = load_crosswalk(settings)
    for message in crosswalk.warnings:
        logger.warning("conditions of use: %s", message)
    return crosswalk


class ConditionsMapper:
    """Maps a facility's activities to conditions of use (callable, see ``ConditionsFor``)."""

    def __init__(self, crosswalk: Crosswalk, settings: ConditionsSettings) -> None:
        self._crosswalk = crosswalk
        self._warned: set[str] = set()
        self.flags = settings.flags

    def __call__(self, activities: frozenset[str], seen: bool) -> Conditions:
        """The conditions of ``activities`` (Form R sections); ``seen`` is whether TRI sent any."""
        if self._crosswalk.unavailable:
            return Conditions(
                [],
                [],
                f"conditions of use unavailable: {self._crosswalk.unavailable}",
            )
        if not seen:
            return Conditions([], [], NO_ACTIVITY_DATA)
        if not activities:
            return Conditions([], [], NO_ACTIVITY)
        found = [c for section in sorted(activities) for c in self._rows(section)]
        if not found:
            return Conditions([], [], NO_ROWS)
        stages = list(dict.fromkeys(c["lifecycle_stage"] for c in found))
        return Conditions([ConditionOfUse(**c) for c in found], stages, None)

    def _rows(self, section: str) -> tuple[ConditionOfUse, ...]:
        rows = self._crosswalk.by_section.get(section, ())
        if not rows and section not in self._warned:
            self._warned.add(section)
            logger.warning("conditions of use: no crosswalk row for Section %s", section)
        return rows
