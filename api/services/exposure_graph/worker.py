"""The worker lane: fugitive release -> indoor air -> inhalation -> shift worker -> limit ratio.

Both ventilation tiers the tool reported are carried; the worst case is the headline.
"""

from __future__ import annotations

from typing import Literal

from api.schemas.exposure_graph import (
    GraphEdge,
    GraphLane,
    GraphNode,
    GraphQuantity,
    GraphStatus,
)
from api.schemas.workspace import Facility, OccupationalExposure, VentilationTier
from api.services.exposure_graph.hub import HUB
from api.services.exposure_graph.parts import LaneParts, edge, fact, joined, quantity, unavailable
from config.exposure_graph import GraphText

LANE = "worker"
RELEASE = f"{LANE}:release"
AIR = f"{LANE}:air"
INHALE = f"{LANE}:inhale"
WORKER = f"{LANE}:receptor"
END = f"{LANE}:endpoint"
Variant = Literal["worst_case", "baseline"]
VARIANTS: tuple[Variant, ...] = ("worst_case", "baseline")
# Relabels the tool's tier onto the shared three-way status; it computes nothing.
TIER_STATUS: dict[str, GraphStatus] = {
    "acceptable": "below",
    "elevated": "near",
    "exceedance": "above",
}


def _tier(worker: OccupationalExposure, variant: Variant) -> VentilationTier:
    return worker.worst_case if variant == "worst_case" else worker.baseline


def _air_quantities(worker: OccupationalExposure, text: GraphText) -> list[GraphQuantity]:
    rows: list[GraphQuantity] = []
    for variant in VARIANTS:
        tier = _tier(worker, variant)
        rows += [
            quantity(
                text,
                "workplace_concentration",
                tier.workplace_concentration_mg_m3,
                variant=variant,
            ),
            quantity(text, "ventilation_rate", tier.ventilation_m3_per_s, variant=variant),
            quantity(text, "mixing_factor", tier.mixing_factor, variant=variant),
        ]
    return rows


def _air_node(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    return GraphNode(
        id=AIR,
        kind="pathway",
        lane=LANE,
        title=text.nodes["indoor_air"],
        headline="workplace_concentration:worst_case",
        quantities=[
            *_air_quantities(worker, text),
            quantity(
                text,
                "vapor_pressure",
                worker.vapor_pressure_mmhg,
                source=worker.vapor_pressure_source,
            ),
        ],
        facts=[fact(text, "ventilation", joined([worker.worst_case.label, worker.baseline.label]))],
    )


def _schedule(
    facility: Facility,
    worker: OccupationalExposure,
    text: GraphText,
) -> list[GraphQuantity]:
    profile = facility.operational_profile
    return [
        quantity(text, "twa", worker.worst_case.twa_mg_m3, variant="worst_case"),
        quantity(text, "operating_days", worker.operating_days_per_year),
        quantity(text, "hours_per_day", worker.hours_per_day),
        quantity(text, "operating_hours", profile.annual_operating_hours if profile else None),
    ]


def _worker_node(facility: Facility, worker: OccupationalExposure, text: GraphText) -> GraphNode:
    profile = facility.operational_profile
    return GraphNode(
        id=WORKER,
        kind="receptor",
        lane=LANE,
        title=text.nodes["shift_worker"],
        headline="twa:worst_case",
        quantities=_schedule(facility, worker, text),
        facts=[
            fact(text, "schedule_source", profile.schedule_source if profile else None),
            fact(text, "assumptions", joined(worker.assumptions)),
        ],
        warnings=list(profile.warnings) if profile else [],
    )


def _endpoint_quantities(worker: OccupationalExposure, text: GraphText) -> list[GraphQuantity]:
    rows = [quantity(text, "oel", worker.oel_twa_mg_m3, source=worker.oel_source)]
    for variant in VARIANTS:
        tier = _tier(worker, variant)
        rows += [
            quantity(text, "oel_ratio", tier.oel_ratio, variant=variant),
            quantity(text, "twa", tier.twa_mg_m3, variant=variant),
            quantity(text, "hq", tier.hq, variant=variant),
            quantity(text, "cancer_risk", tier.cancer_risk, variant=variant),
        ]
    return rows


def _status(worker: OccupationalExposure, text: GraphText) -> tuple[GraphStatus | None, str | None]:
    tier = worker.worst_case.risk_tier
    return (TIER_STATUS[tier], text.tiers[tier]) if tier else (None, None)


def _endpoint(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    status, label = _status(worker, text)
    return GraphNode(
        id=END,
        kind="endpoint",
        lane=LANE,
        title=text.nodes["worker_endpoint"],
        headline="oel_ratio:worst_case",
        quantities=_endpoint_quantities(worker, text),
        facts=[fact(text, "benchmark", worker.oel_source), fact(text, "tier", label)],
        status=status,
        status_label=label,
        warnings=list(worker.warnings),
    )


def _release(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    return GraphNode(
        id=RELEASE,
        kind="release",
        lane=LANE,
        title=text.nodes["fugitive_release"],
        headline="fugitive_release",
        quantities=[quantity(text, "fugitive_release", worker.fugitive_release_kg_per_year)],
    )


def _edges(air: GraphNode, receptor: GraphNode, end: GraphNode) -> tuple[GraphEdge, ...]:
    """Each step to the next, carrying the worst-case concentration, TWA and limit ratio."""
    return (
        edge(LANE, HUB, RELEASE),
        edge(LANE, RELEASE, AIR, air.quantities[0]),
        edge(LANE, AIR, INHALE),
        edge(LANE, INHALE, WORKER, receptor.quantities[0]),
        edge(LANE, WORKER, END, end.quantities[1]),
    )


def worker_lane(facility: Facility, text: GraphText) -> LaneParts:
    """The worker lane of the facility, or an empty lane when it has no occupational result."""
    worker = facility.occupational_exposure
    if worker is None:
        return unavailable(text, LANE)
    route = GraphNode(id=INHALE, kind="route", lane=LANE, title=text.nodes["worker_inhalation"])
    air = _air_node(worker, text)
    receptor = _worker_node(facility, worker, text)
    end = _endpoint(worker, text)
    lane = GraphLane(
        id=LANE,
        label=text.lanes[LANE],
        available=True,
        status=end.status,
        status_label=end.status_label,
    )
    nodes = (_release(worker, text), air, route, receptor, end)
    return LaneParts(lane=lane, nodes=nodes, edges=_edges(air, receptor, end))
