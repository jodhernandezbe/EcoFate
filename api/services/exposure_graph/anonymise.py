"""Leaves a facility's identity out of a lane's text.

The lane builders copy titles, source and warning text from the tools. Should any of it quote the
facility (its name, FRS ID, address, city, state, ZIP code or industry), the text is dropped here,
never reworded (a quoting title becomes the configured withheld title): the run-wide chain names
no facility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from api.schemas.exposure_graph import GraphEdge, GraphFact, GraphNode, GraphQuantity
from api.schemas.workspace import Facility
from api.services.exposure_graph.parts import LaneParts


def _identifiers(facility: Facility) -> list[str]:
    industry = facility.industry.naics_title if facility.industry else None
    fields = (
        facility.name,
        facility.frs_id,
        facility.doc_ctrl_num,
        facility.address,
        facility.city,
        facility.state,
        facility.zip_code,
        facility.naics_subsector_title,
        industry,
    )
    return [field.strip() for field in fields if field and field.strip()]


def _pattern(facility: Facility) -> re.Pattern[str] | None:
    names = _identifiers(facility)
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _quantity(item: GraphQuantity, pattern: re.Pattern[str]) -> GraphQuantity:
    if item.source and pattern.search(item.source):
        return item.model_copy(update={"source": None})
    return item


def _fact(item: GraphFact, pattern: re.Pattern[str], reason: str) -> GraphFact:
    if item.text and pattern.search(item.text):
        return item.model_copy(update={"text": None, "reason": reason})
    return item


@dataclass(frozen=True)
class Withheld:
    """What dropped text is replaced with: a fact's reason and a step's title."""

    reason: str
    title: str


def _node(node: GraphNode, pattern: re.Pattern[str], withheld: Withheld) -> GraphNode:
    reason = withheld.reason
    title = withheld.title if pattern.search(node.title) else node.title
    return node.model_copy(
        update={
            "title": title,
            "quantities": [_quantity(q, pattern) for q in node.quantities],
            "facts": [_fact(f, pattern, reason) for f in node.facts],
            "warnings": [w for w in node.warnings if not pattern.search(w)],
        },
    )


def _edge(edge: GraphEdge, pattern: re.Pattern[str]) -> GraphEdge:
    carried = edge.quantity
    return edge.model_copy(update={"quantity": _quantity(carried, pattern) if carried else None})


def anonymise(parts: LaneParts, facility: Facility, withheld: Withheld) -> LaneParts:
    """The lane without any title, source, fact or warning text that quotes the facility.

    Args:
        parts: The lane as built from the facility.
        facility: The facility whose identity must not appear.
        withheld: The configured reason of a dropped fact and title of a dropped step title.
    """
    pattern = _pattern(facility)
    if pattern is None:
        return parts
    return LaneParts(
        lane=parts.lane,
        nodes=tuple(_node(n, pattern, withheld) for n in parts.nodes),
        edges=tuple(_edge(e, pattern) for e in parts.edges),
    )
