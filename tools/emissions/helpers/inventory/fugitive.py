"""Fold the fugitive air releases into the stack records, and find the fugitive-only facilities.

Fugitive air evaporates inside or beside the plant and mainly exposes its workers. It is read in
its own query, but it is not a stack source: it never enters a stack emission rate. Its release is
converted to kg/yr and put on the record of the facility's stack release; a facility with a
fugitive release and no stack release is returned apart, as a worker-only facility.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from commons.units import UnitConversionError, convert
from tools.schemas import EmissionRecord, FacilityRecord, WorkerOnlyFacility

logger = logging.getLogger(__name__)
_KILOGRAM = "kg"
_FACILITY_KEYS = frozenset(FacilityRecord.__annotations__)


def _kilograms(
    record: EmissionRecord,
    aliases: Mapping[str, str] | None,
) -> float | None:
    try:
        return convert(record["total_release"], record["unit"], _KILOGRAM, aliases)
    except UnitConversionError:
        logger.warning("TRI fugitive release of %s has unit %r", record["frs_id"], record["unit"])
        return None


@dataclass(frozen=True)
class Folded:
    """The stack records, and the facilities with a fugitive release only.

    Attributes:
        stack: Records of the stack media, each with its facility's fugitive release.
        worker_only: Facilities with a fugitive release and no record of the stack media.
    """

    stack: list[EmissionRecord]
    worker_only: list[WorkerOnlyFacility]


def _worker_only(record: EmissionRecord, aliases: Mapping[str, str] | None) -> WorkerOnlyFacility:
    """A fugitive record as a facility with no stack release (and none of its stack fields)."""
    kilograms = _kilograms(record, aliases)
    shared = {k: v for k, v in record.items() if k in _FACILITY_KEYS}
    shared["fugitive_release_kg_per_year"] = kilograms
    shared["fugitive_reporting_year"] = record["reporting_year"] if kilograms is not None else None
    return cast(WorkerOnlyFacility, shared)  # exactly the keys of FacilityRecord, checked by test


def fold_fugitive(
    records: list[EmissionRecord],
    medium: str,
    aliases: Mapping[str, str] | None,
) -> Folded:
    """The records of the other media with their facility's fugitive release (kg/yr), and more.

    Args:
        records: Records of every medium read, one per (medium, facility).
        medium: The fugitive medium, e.g. ``"AIR FUG"``.
        aliases: Source unit spelling -> Pint-parsable unit string.

    Returns:
        ``stack``: the records not of ``medium``, in order, exactly as before, with
        ``fugitive_release_kg_per_year`` and ``fugitive_reporting_year`` set from the facility's
        fugitive record (None when it has none or its unit is not a mass). ``worker_only``: each
        facility with a fugitive record and no record of another medium, with no stack release.
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
    stacked = {r["frs_id"] for r in folded}
    only = [_worker_only(r, aliases) for i, r in fugitive.items() if i not in stacked]
    return Folded(folded, only)
