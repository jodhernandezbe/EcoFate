"""The community lane: each evaluated stack -> outdoor air -> inhalation -> each age band -> HQ."""

from __future__ import annotations

from api.schemas.exposure_graph import GraphEdge, GraphFact, GraphLane, GraphNode, GraphQuantity
from api.schemas.workspace import (
    ExposureRanges,
    Facility,
    Receptors,
    ScenarioReceptor,
    Stack,
    WorstCaseScenario,
)
from api.services.exposure_graph.hub import HUB, release_quantities
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


def _stack_node(
    stack: Stack,
    text: GraphText,
    release: list[GraphQuantity] | None = None,
) -> GraphNode:
    """The stack's node; ``release`` appends the facility's release quantities to it."""
    return GraphNode(
        id=f"{LANE}:stack:{stack.stack_number}",
        kind="release",
        lane=LANE,
        title=text.nodes["stack"].format(number=stack.stack_number),
        headline="stack_peak",
        quantities=[*_stack_quantities(stack, text), *(release or [])],
        facts=[
            fact(text, "stack_tier", stack.tier_label),
            fact(text, "process", stack.scc_description),
        ],
        warnings=list(stack.warnings),
    )


def _generic_release(
    text: GraphText,
    release: list[GraphQuantity] | None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The single release node of a facility with no evaluated stack."""
    node = GraphNode(
        id=f"{LANE}:release",
        kind="release",
        lane=LANE,
        title=text.nodes["stack_release"],
        quantities=release or [],
    )
    return [node], [edge(LANE, HUB, node.id), edge(LANE, node.id, AIR)]


def _releases(
    facility: Facility,
    text: GraphText,
    stack_number: int | None = None,
    release: list[GraphQuantity] | None = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """One node per evaluated stack (only ``stack_number`` when given), or a single release node."""
    stacks = [
        s
        for s in facility.stacks
        if s.stack_number is not None and stack_number in (None, s.stack_number)
    ]
    if not stacks:
        return _generic_release(text, release)
    nodes = [_stack_node(stack, text, release) for stack in stacks]
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


def _highest_band(shares: dict[str, float], doses: dict[str, float]) -> list[str]:
    """The band with the highest reported dose (the first in reported order on a tie), if any."""
    reported = [band for band in shares if band in doses]
    return [max(reported, key=lambda band: doses[band])] if reported else []


def _single_band(people: Receptors, doses: dict[str, float], text: GraphText) -> list[GraphNode]:
    """One receptor node for the most exposed band, with the residents and radius around it."""
    chosen = _highest_band(people.age_distribution, doses)
    if not chosen:
        return [_residents_node(text)]
    node = _band_node(chosen[0], people.age_distribution[chosen[0]], doses[chosen[0]], people, text)
    total = quantity(text, "residents", float(people.total_population))
    radius = quantity(text, "radius", people.radius_km)
    return [node.model_copy(update={"quantities": [*node.quantities, total, radius]})]


def _residents_node(text: GraphText) -> GraphNode:
    title = text.nodes["residents"]
    return GraphNode(id=f"{LANE}:residents", kind="receptor", lane=LANE, title=title)


def _band_nodes(
    facility: Facility,
    exposure: ExposureRanges,
    text: GraphText,
    single_band: bool = False,
) -> list[GraphNode]:
    """One receptor node per age band with residents, or a single one when no band is known.

    ``single_band`` keeps only the band with the highest reported dose.
    """
    people = facility.receptors
    if people is None or not people.age_distribution:
        return [_residents_node(text)]
    doses = exposure.dose.by_band if exposure.dose else {}
    if single_band:
        return _single_band(people, doses, text)
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


def _tract_quantities(
    tracts: list[ScenarioReceptor],
    text: GraphText,
) -> list[GraphQuantity]:
    """Each most affected tract's residents, distance and fraction of the maximum, by position.

    The tract's label, coordinates and bearing are never carried: they would locate the facility.
    """
    rows: list[GraphQuantity] = []
    for position, tract in enumerate(tracts, start=1):
        for key, value in (
            ("tract_residents", None if tract.residents is None else float(tract.residents)),
            ("tract_distance", tract.distance_m),
            ("tract_fraction", tract.fraction_of_maximum),
        ):
            item = quantity(text, key, value)
            label = f"{item.label} {position}"
            rows.append(item.model_copy(update={"key": f"{key}:{position}", "label": label}))
    return rows


def _scenario_extras(
    scenario: WorstCaseScenario,
    text: GraphText,
) -> tuple[list[GraphQuantity], list[GraphFact]]:
    """The tracts, and the note when it says something or stands in for missing tracts."""
    tracts = [r for r in scenario.receptors if r.kind == "tract"]
    note = fact(text, "receptors_note", scenario.receptors_note)
    facts = [note] if note.text is not None or not tracts else []
    return _tract_quantities(tracts, text), facts


def _with_scenario(
    nodes: tuple[GraphNode, ...],
    scenario: WorstCaseScenario,
    text: GraphText,
) -> tuple[GraphNode, ...]:
    """Receptors gain the scenario's most affected tracts and note; the endpoint gains its notes."""
    tracts, facts = _scenario_extras(scenario, text)
    return tuple(_extend(n, scenario, tracts, facts) for n in nodes)


def _extend(
    node: GraphNode,
    scenario: WorstCaseScenario,
    tracts: list[GraphQuantity],
    facts: list[GraphFact],
) -> GraphNode:
    if node.kind == "receptor":
        update = {"quantities": [*node.quantities, *tracts], "facts": [*node.facts, *facts]}
        return node.model_copy(update=update)
    if node.kind == "endpoint":
        return node.model_copy(update={"warnings": [*node.warnings, *scenario.notes]})
    return node


def community_lane(
    facility: Facility,
    text: GraphText,
    *,
    stack_number: int | None = None,
    single_band: bool = False,
    scenario: WorstCaseScenario | None = None,
) -> LaneParts:
    """The fenceline lane of the facility, or an empty lane when it has no community result.

    With ``stack_number`` only that stack's release node is kept, and with ``single_band`` only
    the most exposed age band; each release node then also carries the facility's own release
    quantities (the run-wide chain has no facility node to hold them). The defaults draw
    every stack and band. A ``scenario`` (the run-wide chain passes the driving one) adds its
    most affected tracts and receptors note to the receptor node and its notes to the endpoint.
    """
    exposure = facility.exposure
    if facility.worker_only:
        return unavailable(text, LANE, "worker_only")
    if exposure is None:
        return unavailable(text, LANE)
    release = release_quantities(facility, text) if stack_number or single_band else None
    releases, release_edges = _releases(facility, text, stack_number, release)
    bands = _band_nodes(facility, exposure, text, single_band)
    nodes = (*releases, _air_node(facility, exposure, text), _route(text), *bands)
    nodes = (*nodes, _endpoint(facility, exposure, text))
    if scenario is not None:
        nodes = _with_scenario(nodes, scenario, text)
    edges = (*release_edges, *_receptor_edges(bands))
    lane = GraphLane(id=LANE, label=text.lanes[LANE], available=True, status=facility.status)
    return LaneParts(lane=lane, nodes=nodes, edges=edges)
