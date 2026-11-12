"""Exposure graph contract: how a facility's worst-case exposure arises, as nodes and edges.

Built by ``api/services/exposure_graph/`` from the facility's validated values; nothing in it is
computed. Each quantity carries its own unit (empty for unitless) or, when absent, a reason.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from api.schemas.base import ContractModel
from commons.bands import Band

GraphStatus = Band
NodeKind = Literal["source", "release", "pathway", "route", "receptor", "endpoint"]


class GraphQuantity(ContractModel):
    """A number a tool reported, with its label and unit, or no number and why."""

    key: str
    label: str
    value: float | None = None
    unit: str = ""
    source: str | None = None
    reason: str | None = Field(default=None, description="Why ``value`` is absent.")


class GraphFact(ContractModel):
    """A text value a tool reported (a source, a class, a list), or none and why."""

    key: str
    label: str
    text: str | None = None
    reason: str | None = None


class GraphNode(ContractModel):
    """One step of a lane, or the source facility shared by every lane.

    Attributes:
        lane: Lane id; None for the source facility.
        headline: Key of the quantity shown on the node, when it has one.
        status_label: The status in the lane's own words (the worker tier); None to use the default.
    """

    id: str
    kind: NodeKind
    lane: str | None = None
    title: str
    headline: str | None = None
    quantities: list[GraphQuantity] = Field(default_factory=list[GraphQuantity])
    facts: list[GraphFact] = Field(default_factory=list[GraphFact])
    status: GraphStatus | None = None
    status_label: str | None = None
    warnings: list[str] = Field(default_factory=list[str])


class GraphEdge(ContractModel):
    """A connection from one node to the next, with the quantity it carries when there is one."""

    id: str
    source: str
    target: str
    lane: str
    quantity: GraphQuantity | None = None


class GraphLane(ContractModel):
    """One pathway (community outdoor air, worker indoor air), its status and if it is drawn."""

    id: str
    label: str
    available: bool
    reason: str | None = None
    status: GraphStatus | None = None
    status_label: str | None = None


class ExposureGraph(ContractModel):
    """The source facility, then each lane's steps, joined by labelled edges."""

    lanes: list[GraphLane] = Field(default_factory=list[GraphLane])
    nodes: list[GraphNode] = Field(default_factory=list[GraphNode])
    edges: list[GraphEdge] = Field(default_factory=list[GraphEdge])
