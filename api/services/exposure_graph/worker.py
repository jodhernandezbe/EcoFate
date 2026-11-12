"""The worker lane: driving activity (or OSHA samples) -> workplace air -> inhalation -> worker.

Both cases the tool reported are carried; the worst case is the headline. The TRI fugitive release
is context in the source node, never the source of a value. Every value is as the tool reported it.
"""

from __future__ import annotations

from typing import Literal

from api.schemas.exposure_graph import (
    GraphEdge,
    GraphFact,
    GraphLane,
    GraphNode,
    GraphQuantity,
    GraphStatus,
)
from api.schemas.workspace import (
    Facility,
    MonitoringSummary,
    OccupationalExposure,
    WorkerCase,
)
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


def _case(worker: OccupationalExposure, variant: Variant) -> WorkerCase:
    return worker.worst_case if variant == "worst_case" else worker.baseline


def _activity_quantities(worker: OccupationalExposure, text: GraphText) -> list[GraphQuantity]:
    rows = [
        quantity(
            text,
            "generation_rate",
            _case(worker, variant).generation_g_per_s,
            variant=variant,
        )
        for variant in VARIANTS
    ]
    rows.append(quantity(text, "fugitive_release", worker.fugitive_release_kg_per_year))
    return rows


def _activity_facts(worker: OccupationalExposure, text: GraphText) -> list[GraphFact]:
    driving = worker.driving_activity
    label = driving.label if driving else worker.activity_reason
    return [
        fact(text, "activity", label),
        fact(text, "evidence", text.evidences.get(worker.evidence or "")),
        fact(text, "fugitive_statement", worker.fugitive_statement),
    ]


def _activity_node(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    return GraphNode(
        id=RELEASE,
        kind="release",
        lane=LANE,
        title=text.nodes["worker_activity"],
        headline="generation_rate:worst_case",
        quantities=_activity_quantities(worker, text),
        facts=_activity_facts(worker, text),
        warnings=[w for a in worker.activities if a.key == _key(worker) for w in a.warnings],
    )


def _key(worker: OccupationalExposure) -> str | None:
    return worker.driving_activity.key if worker.driving_activity else None


def _samples(monitoring: MonitoringSummary | None, text: GraphText) -> list[GraphQuantity]:
    m = monitoring
    rows = (
        ("monitoring_samples", m.n_values if m else None),
        ("monitoring_nondetect", m.n_nondetect if m else None),
        ("monitoring_median", m.median_mg_m3 if m else None),
        ("monitoring_p95", m.p95_mg_m3 if m else None),
        ("monitoring_first_year", m.first_year if m else None),
        ("monitoring_last_year", m.last_year if m else None),
    )
    return [quantity(text, key, value) for key, value in rows]


def _monitoring_node(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    m = worker.monitoring
    return GraphNode(
        id=RELEASE,
        kind="release",
        lane=LANE,
        title=text.nodes["monitoring_evidence"],
        headline="monitoring_samples",
        quantities=[
            *_samples(m, text),
            quantity(text, "fugitive_release", worker.fugitive_release_kg_per_year),
        ],
        facts=[
            fact(text, "monitoring_level", m.naics_level if m else worker.monitoring_reason),
            fact(text, "monitoring_source", m.source if m else None),
            fact(text, "fugitive_statement", worker.fugitive_statement),
        ],
        warnings=list(m.statements) if m else [],
    )


def _source_node(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    if worker.evidence == "monitoring":
        return _monitoring_node(worker, text)
    return _activity_node(worker, text)


def _air_quantities(worker: OccupationalExposure, text: GraphText) -> list[GraphQuantity]:
    rows: list[GraphQuantity] = []
    for variant in VARIANTS:
        case = _case(worker, variant)
        rows += [
            quantity(
                text,
                "workplace_concentration",
                case.workplace_concentration_mg_m3,
                variant=variant,
            ),
            quantity(text, "ventilation_rate", case.airflow_m3_per_s, variant=variant),
            quantity(text, "mixing_factor", case.mixing_factor, variant=variant),
            quantity(text, "room_volume", case.room_m3, variant=variant),
            quantity(text, "air_exchanges", case.air_exchange_per_h, variant=variant),
        ]
    return rows


def _case_words(worker: OccupationalExposure, text: GraphText) -> list[str]:
    """For each case, how its average was reached and whether saturation capped the air."""
    parts: list[str] = []
    for variant in VARIANTS:
        case = _case(worker, variant)
        estimator = text.estimators.get(case.estimator or "")
        flag = (
            None if case.capped is None else text.flags["capped" if case.capped else "not_capped"]
        )
        if estimator:
            parts.append(f"{text.variants[variant]}: {joined([estimator, flag or ''])}")
    return parts


def _air_facts(worker: OccupationalExposure, text: GraphText) -> list[GraphFact]:
    setting = worker.worst_case.setting or worker.baseline.setting
    return [
        fact(text, "setting", text.settings.get(setting or "")),
        fact(text, "ventilation", "; ".join(_case_words(worker, text)) or None),
        fact(text, "volatility", text.volatilities.get(worker.volatility or "")),
    ]


def _properties(worker: OccupationalExposure, text: GraphText) -> list[GraphQuantity]:
    return [
        quantity(
            text,
            "vapor_pressure",
            worker.vapor_pressure_mmhg,
            source=worker.vapor_pressure_source,
        ),
        quantity(
            text,
            "molecular_weight",
            worker.molecular_weight,
            source=worker.molecular_weight_source,
        ),
    ]


def _air_node(worker: OccupationalExposure, text: GraphText) -> GraphNode:
    return GraphNode(
        id=AIR,
        kind="pathway",
        lane=LANE,
        title=text.nodes["workplace_air"],
        headline="workplace_concentration:worst_case",
        quantities=[*_air_quantities(worker, text), *_properties(worker, text)],
        facts=_air_facts(worker, text),
    )


def _schedule(
    facility: Facility,
    worker: OccupationalExposure,
    text: GraphText,
) -> list[GraphQuantity]:
    profile = facility.operational_profile
    driving = worker.driving_activity
    return [
        quantity(text, "twa", worker.worst_case.twa_mg_m3, variant="worst_case"),
        quantity(text, "activity_hours", driving.hours if driving else None),
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
        case = _case(worker, variant)
        rows += [
            quantity(text, "oel_ratio", case.oel_ratio, variant=variant),
            quantity(text, "twa", case.twa_mg_m3, variant=variant),
            quantity(text, "hq", case.hq, variant=variant),
            quantity(text, "cancer_risk", case.cancer_risk, variant=variant),
        ]
    return rows


def _status(worker: OccupationalExposure, text: GraphText) -> tuple[GraphStatus | None, str | None]:
    tier = worker.worst_case.risk_tier
    return (tier, text.tiers[tier]) if tier else (None, None)


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
    nodes = (_source_node(worker, text), air, route, receptor, end)
    return LaneParts(lane=lane, nodes=nodes, edges=_edges(air, receptor, end))
