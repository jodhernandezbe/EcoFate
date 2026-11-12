"""Projectors of the emissions tools: inventory, industry, NEI and SCC stacks, SCC lookup."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from api.services.projectors.ledger import Ledger, ToolExchange, text
from api.services.projectors.payloads import (
    EmissionPayload,
    IndustryPayload,
    NeiPayload,
    SccLookupPayload,
    StackPayload,
    decode_json,
    validate,
)
from api.services.projectors.worker_only import note_left_out, place_all


def _rejected(item: object) -> str:
    """The warning for an unplaceable inventory record, naming its FRS ID when it has one."""
    frs_id = cast(Mapping[str, object], item).get("frs_id") if isinstance(item, dict) else None
    who = f"Facility {frs_id}" if isinstance(frs_id, str) else "A facility record"
    return f"{who} was not placed on the map: its coordinates or fields are not valid."


def _inventory_items(exchange: ToolExchange) -> object:
    """Every facility: the complete artifact, else what the model was told (a list or a dict)."""
    if isinstance(exchange.artifact, list):
        return cast(list[object], exchange.artifact)
    value = decode_json(exchange.content)
    return cast(Mapping[str, object], value).get("facilities") if isinstance(value, dict) else value


def _worker_only(exchange: ToolExchange, ledger: Ledger, cas: str | None) -> None:
    """The fugitive-only facilities the model was told about, and how many were left out."""
    value = decode_json(exchange.content)
    if isinstance(value, dict):
        body = cast(Mapping[str, object], value)
        place_all(body.get("worker_only"), ledger, cas)
        note_left_out(body, ledger)


def project_inventory(exchange: ToolExchange, ledger: Ledger) -> None:
    """One facility per FRS ID; a later result replaces an earlier record of the same facility."""
    items = _inventory_items(exchange)
    if not isinstance(items, list):
        ledger.skip(exchange, "its result was not a list of facilities")
        return
    ledger.note_cas(exchange)
    cas = text(exchange.args, "cas_number")
    _worker_only(exchange, ledger, cas)
    for item in cast(list[object], items):
        record = validate(EmissionPayload, item)
        if record is None:
            ledger.warnings.append(_rejected(item))
        else:
            ledger.facilities[record.frs_id] = record
            if cas is not None:
                ledger.facility_cas[record.frs_id] = cas


def project_industry(exchange: ToolExchange, ledger: Ledger) -> None:
    """The industry of the submission with the document control number the model passed."""
    doc_ctrl_num = text(exchange.args, "doc_ctrl_num")
    industry = ledger.read(exchange, IndustryPayload)
    if industry is not None and doc_ctrl_num is not None:
        ledger.industries.append((doc_ctrl_num, industry))


def project_nei(exchange: ToolExchange, ledger: Ledger) -> None:
    """The NEI stack candidates of the facility with the FRS ID the model passed."""
    frs_id = text(exchange.args, "frs_id")
    result = ledger.read(exchange, NeiPayload)
    if result is not None and frs_id is not None:
        ledger.nei.append((frs_id, result.candidates))


def project_scc_stack(exchange: ToolExchange, ledger: Ledger) -> None:
    """A PSTK or default stack; it is tied to a facility later, through the exposure result."""
    stack = ledger.read(exchange, StackPayload)
    if stack is not None:
        ledger.scc_stacks.append(stack)


def project_scc_lookup(exchange: ToolExchange, ledger: Ledger) -> None:
    """The SCC matches returned; the latest result for an SCC wins."""
    lookup = ledger.read(exchange, SccLookupPayload)
    for match in lookup.matches if lookup else ():
        ledger.scc_matches[match.scc] = match
