"""Operational profile of a facility: schedule, life cycle stage, condition of use, CDR sector.

A plain function of an inventory record, not a tool the model calls: the batch assessment
composes it with the exposure results (it may use a tool folder's public modules, not its
helpers). The logic is in ``helpers/inventory/profile.py``; this supplies the shipped settings.
"""

from __future__ import annotations

from config.cdr_sector import get_cdr_sector_settings
from config.plant_hours import get_plant_hours_settings
from tools.emissions.helpers.inventory.profile import build_profile
from tools.emissions.helpers.inventory.sector import get_sector_table
from tools.schemas import FacilityRecord, OperationalProfile


def operational_profile(record: FacilityRecord) -> OperationalProfile:
    """The operational profile of an inventory record, from the shipped settings and tables.

    Args:
        record: One facility's inventory record; its operating hours per year (h/yr) give the
            schedule, its TRI activities the life cycle stages and conditions of use, and its
            NAICS code the CDR industrial sector.

    Returns:
        The profile; a value is None, with a warning, when its source does not give it.
    """
    sector_settings = get_cdr_sector_settings()
    return build_profile(
        record,
        get_plant_hours_settings(),
        sector_settings,
        get_sector_table(sector_settings),
    )
