"""The exposure graph of a facility: the source, then one lane per pathway, built from its values.

A new pathway is one module with a ``(Facility, GraphText) -> LaneParts`` function, added to
``LANES``; the frontend draws whatever lanes the graph holds.
"""

from __future__ import annotations

from collections.abc import Callable

from api.schemas.exposure_graph import ExposureGraph
from api.schemas.workspace import Facility
from api.services.exposure_graph.community import community_lane
from api.services.exposure_graph.hub import hub_node
from api.services.exposure_graph.parts import LaneParts
from api.services.exposure_graph.worker import worker_lane
from config.exposure_graph import GraphText

LaneBuilder = Callable[[Facility, GraphText], LaneParts]
LANES: tuple[LaneBuilder, ...] = (community_lane, worker_lane)


def build_exposure_graph(
    facility: Facility,
    text: GraphText,
    lanes: tuple[LaneBuilder, ...] = LANES,
) -> ExposureGraph:
    """The facility's graph; a lane without its result is kept and marked unavailable."""
    parts = [build(facility, text) for build in lanes]
    return ExposureGraph(
        lanes=[p.lane for p in parts],
        nodes=[hub_node(facility, text), *(n for p in parts for n in p.nodes)],
        edges=[e for p in parts for e in p.edges],
    )
