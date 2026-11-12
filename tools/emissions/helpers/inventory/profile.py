"""Operational profile of a facility from its inventory record and explicit reference tables.

The schedule, TSCA life cycle stage, condition of use and CDR industrial sector. The shipped
settings are supplied by ``tools.emissions.profile``; tests pass their own.
"""

from __future__ import annotations

from config.cdr_sector import CdrSectorSettings
from config.plant_hours import PlantHoursSettings
from tools.emissions.helpers.inventory.schedule import Schedule, schedule_from_hours
from tools.emissions.helpers.inventory.sector import SectorTable, sector_for
from tools.schemas import FacilityRecord, OperationalProfile

_DERIVED = "days per week derived from the hours per week and a configured working day"


def _schedule(
    record: FacilityRecord,
    settings: PlantHoursSettings,
) -> tuple[Schedule | None, str | None]:
    try:
        return schedule_from_hours(record["operating_hours_per_year"], settings), None
    except ValueError as error:
        return None, f"no schedule: {error}"


def _categories(record: FacilityRecord) -> list[str]:
    seen: dict[str, None] = {}
    for use in record["conditions_of_use"]:
        seen.setdefault(use["cou_category"])
    return list(seen)


def build_profile(
    record: FacilityRecord,
    plant: PlantHoursSettings,
    sector_settings: CdrSectorSettings,
    table: SectorTable,
) -> OperationalProfile:
    """The profile of ``record`` from explicit settings (for tests and the default builder)."""
    schedule, problem = _schedule(record, plant)
    sector, why = sector_for(record["naics_code"], table, sector_settings)
    warnings = [w for w in (problem, why, record["conditions_note"]) if w]
    return OperationalProfile(
        naics_code=record["naics_code"],
        life_cycle_stage=list(record["lifecycle_stages"]),
        cou_category=_categories(record),
        cdr_sector=sector,
        days_per_week=schedule.days_per_week if schedule else None,
        operating_days_per_year=schedule.operating_days_per_year if schedule else None,
        hours_per_day=schedule.hours_per_day if schedule else None,
        annual_operating_hours=schedule.annual_operating_hours if schedule else None,
        schedule_source=f"{record['operating_hours_source']}; {_DERIVED}",
        warnings=warnings,
    )
