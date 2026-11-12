"""The workspace of a thread: rebuilt from its tool calls and results alone.

Pure functions. The state never comes from assistant prose; a result that is malformed, in error
or unattributable is left out with a warning and never raises.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from api.schemas.workspace import Facility, RiskSummary, WorkspaceState
from api.services.projectors import PROJECTORS
from api.services.projectors.facilities import build_facilities, meteorology_view
from api.services.projectors.framing import bounds, framing_key, next_version
from api.services.projectors.ledger import Ledger, ToolExchange
from api.services.projectors.rules import WorkspaceRules
from api.services.projectors.summary import (
    chemical,
    risk_summary,
    scenario_drivers,
    select,
    worker_summary,
)
from api.services.projectors.supplied import apply_supplied
from api.services.projectors.worker_only import left_out_notes


def pair_exchanges(messages: Sequence[BaseMessage]) -> list[ToolExchange]:
    """Tool calls paired with their results by call id, in the order the results arrived.

    A call without a result, a result without a call and a result that is an error are dropped.
    """
    calls = {
        str(call["id"]): call
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    return [
        ToolExchange(
            name=call["name"],
            args=call["args"],
            content=message.content,
            artifact=message.artifact,
        )
        for message in messages
        if isinstance(message, ToolMessage)
        and message.status != "error"
        and (call := calls.get(message.tool_call_id)) is not None
    ]


def _fill(exchanges: Sequence[ToolExchange], ledger: Ledger) -> None:
    for exchange in exchanges:
        projector = PROJECTORS.get(exchange.name)
        if projector is not None:
            projector(exchange, ledger)


def _ribbon(chosen: Facility | None, summary: RiskSummary, ledger: Ledger) -> dict[str, object]:
    """What the ribbon shows: the chemical, the highest risk and the selected facility's context."""
    latest = ledger.meteorology[-1] if ledger.meteorology else None
    weather = chosen.meteorology if chosen else None
    return {
        "selected_frs_id": chosen.frs_id if chosen else None,
        "chemical": chemical(ledger),
        "risk": summary,
        "receptors": chosen.receptors if chosen else None,
        "meteorology": weather or (meteorology_view(latest) if latest else None),
    }


def _framing(facilities: Sequence[Facility], previous: WorkspaceState | None) -> dict[str, object]:
    before = (previous.framing_version, framing_key(previous.facilities)) if previous else None
    return {"framing_version": next_version(before, facilities), "bounds": bounds(facilities)}


def build_workspace(
    messages: Sequence[BaseMessage],
    rules: WorkspaceRules,
    previous: WorkspaceState | None = None,
    supplied: Mapping[str, float] | None = None,
) -> WorkspaceState:
    """The workspace shown for a thread's messages.

    Args:
        messages: The thread's messages (only tool calls and their results are read).
        rules: Thresholds, attribution tolerance and default radius from configuration.
        previous: The workspace sent before, so the framing version moves only on real changes.
        supplied: The benchmark values the user entered in this thread, by entry ID.
    """
    exchanges = pair_exchanges(messages)
    ledger = Ledger(default_radius_km=rules.default_radius_km)
    _fill(exchanges, ledger)
    apply_supplied(ledger, supplied or {})
    facilities, lost = build_facilities(ledger, rules)
    exposed = any(e.name == "calculate_exposure_metrics" for e in exchanges)
    summary = risk_summary(facilities, rules, exposed)
    return WorkspaceState.model_validate(
        {
            **_ribbon(select(facilities, summary), summary, ledger),
            **_framing(facilities, previous),
            "worker_risk": worker_summary(facilities),
            "scenario_drivers": scenario_drivers(facilities),
            "facilities": facilities,
            "unattributed": lost,
            "warnings": [*ledger.warnings, *left_out_notes(ledger)],
        },
    )
