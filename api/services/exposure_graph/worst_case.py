"""The run-wide worst-case chain: one lane per pathway, from the facility that drives it.

Each lane is built by the ordinary lane builder with a branch selection (the driver's stack, the
most exposed age band, the worst-case ventilation only) from the facility named by the driver of
the pathway's headline quantity. The chain names no facility. A new pathway is one
``WorstCaseLane``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from api.schemas.exposure_graph import ExposureGraph, GraphNode
from api.schemas.workspace import Chemical, Facility, ScenarioDriver
from api.services.exposure_graph.anonymise import Withheld, anonymise
from api.services.exposure_graph.community import community_lane
from api.services.exposure_graph.hub import worst_case_hub
from api.services.exposure_graph.parts import LaneParts, unavailable
from api.services.exposure_graph.worker import worker_lane
from config.exposure_graph import GraphText

Selector = Callable[[Facility, GraphText, ScenarioDriver], LaneParts]


@dataclass(frozen=True)
class WorstCaseLane:
    """One lane of the chain.

    Attributes:
        lane: Lane id (a key of the configured lane labels).
        pathway_key: The scenario pathway whose drivers feed the lane.
        select: Builds the lane from the driving facility, keeping only the worst-case branch.
    """

    lane: str
    pathway_key: str
    select: Selector


def _community(facility: Facility, text: GraphText, driver: ScenarioDriver) -> LaneParts:
    scenario = next(
        (
            s
            for s in facility.scenarios
            if (s.pathway_key, s.quantity) == (driver.pathway_key, driver.quantity)
        ),
        None,
    )
    return community_lane(
        facility,
        text,
        stack_number=driver.stack_number,
        single_band=True,
        scenario=scenario,
    )


def _worker(facility: Facility, text: GraphText, driver: ScenarioDriver) -> LaneParts:
    return worker_lane(facility, text, variants=("worst_case",))


WORST_CASE_LANES: tuple[WorstCaseLane, ...] = (
    WorstCaseLane("community", "community_inhalation", _community),
    WorstCaseLane("worker", "worker_inhalation", _worker),
)


def _headline_driver(
    spec: WorstCaseLane,
    drivers: Sequence[ScenarioDriver],
    text: GraphText,
) -> ScenarioDriver | None:
    quantity = text.worst_case.headline[spec.pathway_key]
    return next(
        (d for d in drivers if d.pathway_key == spec.pathway_key and d.quantity == quantity),
        None,
    )


def _notes(
    spec: WorstCaseLane,
    headline: ScenarioDriver,
    drivers: Sequence[ScenarioDriver],
    text: GraphText,
) -> list[str]:
    """One note for each other quantity of the pathway that another facility drives."""
    others = [
        d
        for d in drivers
        if d.pathway_key == spec.pathway_key
        and d.quantity != headline.quantity
        and d.frs_id != headline.frs_id
    ]
    words = text.worst_case.other_driver_note
    return [words.format(quantity=_label(d.quantity, text)) for d in others]


def _label(quantity: str, text: GraphText) -> str:
    configured = text.quantities.get(quantity)
    return configured.label if configured else quantity


def _with_notes(parts: LaneParts, lane: str, notes: list[str]) -> LaneParts:
    """The lane's endpoint with the notes added to its warnings."""
    if not notes:
        return parts
    nodes = tuple(
        n.model_copy(update={"warnings": [*n.warnings, *notes]})
        if n.kind == "endpoint" and n.lane == lane
        else n
        for n in parts.nodes
    )
    return LaneParts(lane=parts.lane, nodes=nodes, edges=parts.edges)


def _lane(
    spec: WorstCaseLane,
    by_frs_id: dict[str, Facility],
    drivers: Sequence[ScenarioDriver],
    text: GraphText,
) -> LaneParts:
    headline = _headline_driver(spec, drivers, text)
    facility = by_frs_id.get(headline.frs_id) if headline else None
    if headline is None or facility is None:
        return unavailable(text, spec.lane)
    parts = spec.select(facility, text, headline)
    withheld = Withheld(text.reasons["missing"], text.worst_case.withheld_title)
    parts = anonymise(parts, facility, withheld)
    return _with_notes(parts, spec.lane, _notes(spec, headline, drivers, text))


def _source(parts: Sequence[LaneParts], chemical: Chemical, text: GraphText) -> list[GraphNode]:
    return [worst_case_hub(chemical, text)] if any(p.lane.available for p in parts) else []


def build_worst_case_chain(
    facilities: Sequence[Facility],
    drivers: Sequence[ScenarioDriver],
    text: GraphText,
    chemical: Chemical,
) -> ExposureGraph:
    """The anonymous worst-case graph of the run; empty when there are no scenario drivers.

    Args:
        facilities: The run's facilities.
        drivers: The scenario drivers (each pathway quantity with its driving facility).
        text: Fixed text and units, including each pathway's headline quantity.
        chemical: The queried chemical (its CAS number and name are the source's only facts).
    """
    if not drivers:
        return ExposureGraph()
    by_frs_id = {f.frs_id: f for f in facilities}
    parts = [_lane(spec, by_frs_id, drivers, text) for spec in WORST_CASE_LANES]
    return ExposureGraph(
        caption=text.worst_case.caption,
        lanes=[p.lane for p in parts],
        nodes=[*_source(parts, chemical, text), *(n for p in parts for n in p.nodes)],
        edges=[e for p in parts for e in p.edges],
    )
