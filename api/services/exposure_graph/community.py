"""The community lane: each evaluated stack -> outdoor air -> inhalation -> each age band -> HQ."""

from __future__ import annotations

from api.schemas.exposure_graph import GraphEdge, GraphLane, GraphNode, GraphQuantity
from api.schemas.workspace import ExposureRanges, Facility, Receptors, Stack
from api.services.exposure_graph.hub import HUB
from api.services.exposure_graph.parts import LaneParts, edge, fact, quantity, unavailable
from config.exposure_graph import GraphText

LANE = "community"
AIR = f"{LANE}:air"
INHALE = f"{LANE}:inhale"
END = f"{LANE}:endpoint"


def _stack_quantities(stack: Stack, text: GraphText) -> list[GraphQuantity]:
    scenario = stack.worst_case
    return [
        quantity(text, "stack_peak", scenario.max_concentration_ug_m3 if scenario else None),
        quantity(text, "peak_distance", scenario.distance_m if scenario else None),
        quantity(text, "stack_height", stack.height_m),
        quantity(text, "stack_diameter", stack.diameter_m),
        quantity(text, "exit_velocity", stack.exit_velocity_m_s),
        quantity(text, "exit_temperature", stack.exit_temperature_k),
    ]


def _stack_node(stack: Stack, text: GraphText) -> GraphNode:
    return GraphNode(
        id=f"{LANE}:stack:{stack.stack_number}",
        kind="release",
        lane=LANE,
        title=text.nodes["stack"].format(number=stack.stack_number),
        headline="stack_peak",
        quantities=_stack_quantities(stack, text),
        facts=[
            fact(text, "stack_tier", stack.tier_label),
            fact(text, "process", stack.scc_description),
        ],
        warnings=list(stack.warnings),
    )


def _releases(facility: Facility, text: GraphText) -> tuple[list[GraphNode], list[GraphEdge]]:
    """One node per evaluated stack, or a single release node when none was evaluated."""
    stacks = [s for s in facility.stacks if s.stack_number is not None]
    if not stacks:
        title = text.nodes["stack_release"]
        node = GraphNode(id=f"{LANE}:release", kind="release", lane=LANE, title=title)
        return [node], [edge(LANE, HUB, node.id), edge(LANE, node.id, AIR)]
    nodes = [_stack_node(stack, text) for stack in stacks]
    edges = [edge(LANE, HUB, n.id) for n in nodes]
    edges += [edge(LANE, n.id, AIR, n.quantities[0]) for n in nodes]
    return nodes, edges


def _peak_distance(facility: Facility, exposure: ExposureRanges) -> float | None:
    """The distance the tool reported for the stack that gave the peak concentration."""
    peak = exposure.concentration_worst
    worst = next((s for s in facility.stacks if peak and s.stack_number == peak.high_stack), None)
    return worst.worst_case.distance_m if worst and worst.worst_case else None


def _air_quantities(
    facility: Facility,
    exposure: ExposureRanges,
    text: GraphText,
) -> list[GraphQuantity]:
    peak = exposure.concentration_worst
    weather = facility.meteorology
    return [
        quantity(text, "peak_concentration", peak.high if peak else None),
        quantity(text, "peak_distance", _peak_distance(facility, exposure)),
        quantity(text, "wind_speed", weather.wind_speed_m_s if weather else None),
    ]


def _air_node(facility: Facility, exposure: ExposureRanges, text: GraphText) -> GraphNode:
    weather = facility.meteorology
    return GraphNode(
        id=AIR,
        kind="pathway",
        lane=LANE,
        title=text.nodes["outdoor_air"],
        headline="peak_concentration",
        quantities=_air_quantities(facility, exposure, text),
        facts=[
            fact(text, "stability_class", weather.stability_class if weather else None),
            fact(text, "weather_source", weather.source if weather else None),
        ],
        warnings=list(exposure.warnings),
    )


def _band_node(
    band: str,
    share: float,
    dose: float | None,
    people: Receptors,
    text: GraphText,
) -> GraphNode:
    return GraphNode(
        id=f"{LANE}:band:{band}",
        kind="receptor",
        lane=LANE,
        title=text.nodes["age_band"].format(band=band),
        headline="band_dose",
        quantities=[quantity(text, "band_dose", dose), quantity(text, "band_share", share)],
        facts=[fact(text, "population_source", people.source)],
        warnings=list(people.warnings),
    )


def _band_nodes(facility: Facility, exposure: ExposureRanges, text: GraphText) -> list[GraphNode]:
    """One receptor node per age band with residents, or a single one when no band is known."""
    people = facility.receptors
    if people is None or not people.age_distribution:
        title = text.nodes["residents"]
        return [GraphNode(id=f"{LANE}:residents", kind="receptor", lane=LANE, title=title)]
    doses = exposure.dose.by_band if exposure.dose else {}
    return [
        _band_node(band, share, doses.get(band), people, text)
        for band, share in people.age_distribution.items()
    ]


def _risks(facility: Facility, exposure: ExposureRanges, text: GraphText) -> list[GraphQuantity]:
    people = facility.receptors
    cancer = exposure.cancer_risk_worst
    return [
        quantity(text, "hq", exposure.hq_worst.high if exposure.hq_worst else None),
        quantity(text, "cancer_risk", cancer.high if cancer else None),
        quantity(text, "residents", float(people.total_population) if people else None),
        quantity(text, "radius", people.radius_km if people else None),
    ]


def _endpoint(facility: Facility, exposure: ExposureRanges, text: GraphText) -> GraphNode:
    return GraphNode(
        id=END,
        kind="endpoint",
        lane=LANE,
        title=text.nodes["community_endpoint"],
        headline="hq",
        quantities=_risks(facility, exposure, text),
        status=facility.status,
    )


def _route(text: GraphText) -> GraphNode:
    return GraphNode(id=INHALE, kind="route", lane=LANE, title=text.nodes["outdoor_inhalation"])


def _receptor_edges(bands: list[GraphNode]) -> list[GraphEdge]:
    """Air to the route, the route to each receptor with its dose, each receptor to the endpoint."""
    return [
        edge(LANE, AIR, INHALE),
        *(edge(LANE, INHALE, b.id, b.quantities[0] if b.quantities else None) for b in bands),
        *(edge(LANE, b.id, END) for b in bands),
    ]


def community_lane(facility: Facility, text: GraphText) -> LaneParts:
    """The fenceline lane of the facility, or an empty lane when it has no community result."""
    exposure = facility.exposure
    if facility.worker_only:
        return unavailable(text, LANE, "worker_only")
    if exposure is None:
        return unavailable(text, LANE)
    releases, release_edges = _releases(facility, text)
    bands = _band_nodes(facility, exposure, text)
    edges = (*release_edges, *_receptor_edges(bands))
    nodes = (
        *releases,
        _air_node(facility, exposure, text),
        _route(text),
        *bands,
        _endpoint(facility, exposure, text),
    )
    lane = GraphLane(id=LANE, label=text.lanes[LANE], available=True, status=facility.status)
    return LaneParts(lane=lane, nodes=nodes, edges=edges)
