"""Fold the fugitive air releases into the stack records of the same facilities.

Fugitive air evaporates inside or beside the plant and mainly exposes its workers. It is read in
its own query, but it is not a stack source: it never becomes a facility of its own and never
enters a stack emission rate. Its release is converted to kg/yr and put on the facility's record.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from commons.units import UnitConversionError, convert
from tools.schemas import EmissionRecord

logger = logging.getLogger(__name__)
_KILOGRAM = "kg"


def _kilograms(
    record: EmissionRecord,
    aliases: Mapping[str, str] | None,
) -> float | None:
    try:
        return convert(record["total_release"], record["unit"], _KILOGRAM, aliases)
    except UnitConversionError:
        logger.warning("TRI fugitive release of %s has unit %r", record["frs_id"], record["unit"])
        return None


def fold_fugitive(
    records: list[EmissionRecord],
    medium: str,
    aliases: Mapping[str, str] | None,
) -> list[EmissionRecord]:
    """The records of the other media, each with its facility's fugitive release (kg/yr).

    Args:
        records: Records of every medium read, one per (medium, facility).
        medium: The fugitive medium, e.g. ``"AIR FUG"``.
        aliases: Source unit spelling -> Pint-parsable unit string.

    Returns:
        The records not of ``medium``, in order, with ``fugitive_release_kg_per_year`` and
        ``fugitive_reporting_year`` set from the facility's fugitive record (None when it has
        none or its unit is not a mass). A facility with only a fugitive release is dropped.
    """
    fugitive = {r["frs_id"]: r for r in records if r["environmental_medium"] == medium}
    folded: list[EmissionRecord] = []
    for record in records:
        if record["environmental_medium"] == medium:
            continue
        found = fugitive.get(record["frs_id"])
        kilograms = _kilograms(found, aliases) if found is not None else None
        year = found["reporting_year"] if found is not None and kilograms is not None else None
        folded.append(
            {**record, "fugitive_release_kg_per_year": kilograms, "fugitive_reporting_year": year},
        )
    return folded
