"""Fugitive-only facilities: placed on the workspace with no community result.

A facility with a fugitive air release and no stack release is never a stack source. It is placed
(from the inventory or the batch assessment) so its worker result can be shown; the inventory's
count of those left beyond its cap becomes one note on the workspace.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from api.services.projectors.ledger import Ledger
from api.services.projectors.payloads import WorkerOnlyFacilityPayload, validate

LEFT_OUT_KEY = "worker_only_left_out"


def rejected(item: object) -> str:
    """The warning for an unplaceable fugitive-only record."""
    frs_id = cast(Mapping[str, object], item).get("frs_id") if isinstance(item, dict) else None
    who = f"Worker-only facility {frs_id}" if isinstance(frs_id, str) else "A worker-only facility"
    return f"{who} was not placed on the map: its coordinates or fields are not valid."


def place(record: WorkerOnlyFacilityPayload, ledger: Ledger, cas: str | None) -> bool:
    """File the record unless a stack source holds that FRS ID (a real result is never replaced)."""
    if record.frs_id in ledger.facilities:
        return False
    ledger.worker_only[record.frs_id] = record
    if cas is not None:
        ledger.facility_cas[record.frs_id] = cas
    return True


def place_all(raws: object, ledger: Ledger, cas: str | None) -> None:
    """Every valid fugitive-only record of an inventory result; an invalid one warns alone."""
    if not isinstance(raws, list):
        return
    for raw in cast(list[object], raws):
        record = validate(WorkerOnlyFacilityPayload, raw)
        if record is None:
            ledger.warnings.append(rejected(raw))
        else:
            place(record, ledger, cas)


def note_left_out(body: Mapping[str, object], ledger: Ledger) -> None:
    """Remember how many fugitive-only facilities were left beyond the cap (never a bool)."""
    count = body.get(LEFT_OUT_KEY)
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        ledger.worker_only_left_out = count


def left_out_notes(ledger: Ledger) -> list[str]:
    """The note for the facilities beyond the cap; empty when none were."""
    count = ledger.worker_only_left_out
    if count <= 0:
        return []
    return [
        f"{count} more worker-only facilities (fugitive air release, no stack release) were "
        "left out of the inventory's list.",
    ]
