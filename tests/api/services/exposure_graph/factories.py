"""Shared fixtures of the exposure graph tests: a facility, its stacks and the tools' values."""

from __future__ import annotations

from api.schemas.exposure_graph import ExposureGraph, GraphNode, GraphQuantity
from api.schemas.workspace import Facility
from config.ui import get_ui_settings
from tests.api.services.projectors.factories import worker_case, worker_result

TEXT = get_ui_settings().exposure_graph
MISSING = TEXT.reasons["missing"]


WORKER = worker_result(
    baseline=worker_case(oel_ratio=0.1, risk_tier="low", cancer_risk=None),
    worst_case=worker_case(
        estimator="two_zone",
        airflow_m3_per_s=None,
        mixing_factor=None,
        room_m3=50.0,
        air_exchange_per_h=4.0,
        oel_ratio=2.0,
        risk_tier="high",
        cancer_risk=None,
        twa_mg_m3=3.0,
    ),
    rfc=None,
    iur=None,
)


def stack_dict(number: int, peak: float) -> dict[str, object]:
    return {
        "stack_number": number,
        "height_m": 10.0,
        "tier": 3,
        "tier_label": "Tier 3",
        "worst_case": {"max_concentration_ug_m3": peak, "distance_m": 100.0 * number},
    }


EXPOSURE: dict[str, object] = {
    "hq_worst": {"low": 0.5, "high": 2.0, "low_stack": 1, "high_stack": 2},
    "concentration_worst": {"low": 1.0, "high": 4.0, "low_stack": 1, "high_stack": 2},
    "dose": {
        "highest_mg_kg_day": 0.3,
        "highest_band": "0-4",
        "by_band": {"0-4": 0.3, "18-64": 0.1},
    },
    "stacks_given": 2,
    "stacks_evaluated": 2,
}
PEOPLE: dict[str, object] = {
    "total_population": 1000,
    "radius_km": 2.0,
    "age_distribution": {"0-4": 10.0, "18-64": 90.0},
    "source": "synthetic census",
    "screening_default": False,
}


def facility(**over: object) -> Facility:
    base: dict[str, object] = {
        "frs_id": "F1",
        "name": "Plant F1",
        "latitude": 1.0,
        "longitude": 2.0,
        "medium": "AIR STACK",
        "reporting_year": 2020,
        "total_release": 100.0,
        "release_unit": "Pounds",
        "emission_rate_g_s": 1.0,
        "operating_hours_per_year": 8760.0,
        "status": "high",
    }
    return Facility.model_validate({**base, **over})


def node(graph: ExposureGraph, node_id: str) -> GraphNode:
    return next(n for n in graph.nodes if n.id == node_id)


def value(node: GraphNode, key: str) -> GraphQuantity:
    return next(q for q in node.quantities if q.key == key)
