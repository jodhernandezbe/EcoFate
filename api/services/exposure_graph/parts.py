"""Small builders shared by the lanes: a labelled quantity, a fact, an edge and a lane's output.

Values are passed through as the validated facility holds them; nothing is computed or converted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from api.schemas.exposure_graph import GraphEdge, GraphFact, GraphLane, GraphNode, GraphQuantity
from config.exposure_graph import GraphText


@dataclass(frozen=True)
class LaneParts:
    """What one lane adds to the graph."""

    lane: GraphLane
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()


def quantity(
    text: GraphText,
    key: str,
    value: float | None,
    *,
    unit: str | None = None,
    source: str | None = None,
    variant: str | None = None,
) -> GraphQuantity:
    """The configured label and unit around a reported value; absent values carry the reason."""
    configured = text.quantities[key]
    label = f"{configured.label} ({text.variants[variant]})" if variant else configured.label
    return GraphQuantity(
        key=f"{key}:{variant}" if variant else key,
        label=label,
        value=value,
        unit=configured.unit if unit is None else unit,
        source=source,
        reason=None if value is not None else text.reasons["missing"],
    )


def fact(text: GraphText, key: str, value: str | None) -> GraphFact:
    """A reported text value under its configured label; blank or absent carries the reason."""
    kept = value.strip() if value else None
    return GraphFact(
        key=key,
        label=text.facts[key],
        text=kept or None,
        reason=None if kept else text.reasons["missing"],
    )


def joined(items: Sequence[str]) -> str | None:
    """The distinct non-blank items, in order, joined; None when there are none."""
    kept = list(dict.fromkeys(item.strip() for item in items if item.strip()))
    return ", ".join(kept) or None


def edge(lane: str, source: str, target: str, carried: GraphQuantity | None = None) -> GraphEdge:
    """A connection from ``source`` to ``target`` in ``lane``, with the quantity it carries."""
    return GraphEdge(
        id=f"{source}->{target}",
        source=source,
        target=target,
        lane=lane,
        quantity=carried,
    )


def unavailable(text: GraphText, lane: str) -> LaneParts:
    """A lane drawn empty, with the configured reason."""
    return LaneParts(
        lane=GraphLane(id=lane, label=text.lanes[lane], available=False, reason=text.reasons[lane]),
    )
