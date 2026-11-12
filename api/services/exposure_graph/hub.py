"""The source facility node: who releases the chemical, how much, and under what use."""

from __future__ import annotations

from api.schemas.exposure_graph import GraphFact, GraphNode, GraphQuantity
from api.schemas.workspace import Facility
from api.services.exposure_graph.parts import fact, joined, quantity
from config.exposure_graph import GraphText

HUB = "source"


def _place(facility: Facility) -> str | None:
    return joined([part for part in (facility.city, facility.state) if part])


def _industry(facility: Facility) -> str | None:
    if facility.naics_subsector_title:
        return facility.naics_subsector_title
    return facility.industry.naics_title if facility.industry else None


def _quantities(facility: Facility, text: GraphText) -> list[GraphQuantity]:
    hours = facility.operating_hours_per_year
    if facility.worker_only:
        fugitive = quantity(text, "fugitive_release", facility.fugitive_release_kg_per_year)
        return [
            fugitive,
            quantity(text, "operating_hours", hours, source=facility.operating_hours_source),
        ]
    return [
        quantity(text, "total_release", facility.total_release, unit=facility.release_unit),
        quantity(text, "emission_rate", facility.emission_rate_g_s),
        quantity(text, "operating_hours", hours, source=facility.operating_hours_source),
    ]


def _facts(facility: Facility, text: GraphText) -> list[GraphFact]:
    uses = joined([c.cou_category for c in facility.conditions_of_use])
    return [
        fact(text, "cas_number", facility.cas_number),
        fact(text, "location", _place(facility)),
        fact(text, "industry", _industry(facility)),
        fact(text, "condition_of_use", uses),
        fact(text, "life_cycle_stage", joined(facility.lifecycle_stages)),
    ]


def hub_node(facility: Facility, text: GraphText) -> GraphNode:
    """The node every lane starts from."""
    return GraphNode(
        id=HUB,
        kind="source",
        title=facility.name or facility.frs_id,
        headline="fugitive_release" if facility.worker_only else "total_release",
        quantities=_quantities(facility, text),
        facts=_facts(facility, text),
    )
