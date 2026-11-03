"""Projectors: one small function per tool that files its validated result in the ledger.

``PROJECTORS`` is the table the serializer dispatches on (a new tool is one entry); a test
checks every key is a registered tool, so a renamed tool fails loudly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from api.services.projectors.assessment import project_assessment
from api.services.projectors.chemistry import (
    project_category,
    project_properties,
    project_read_across,
)
from api.services.projectors.emissions import (
    project_industry,
    project_inventory,
    project_nei,
    project_scc_lookup,
    project_scc_stack,
)
from api.services.projectors.exposure import (
    project_exposure,
    project_meteorology,
    project_population,
)
from api.services.projectors.ledger import Ledger, ToolExchange

Projector = Callable[[ToolExchange, Ledger], None]

PROJECTORS: Mapping[str, Projector] = MappingProxyType(
    {
        "fetch_chemical_properties": project_properties,
        "find_tri_category": project_category,
        "find_tri_read_across_surrogate": project_read_across,
        "query_emissions_inventory": project_inventory,
        "fetch_facility_industry": project_industry,
        "lookup_scc_process_description": project_scc_lookup,
        "fetch_stack_parameters_from_nei": project_nei,
        "fetch_stack_parameters_from_scc": project_scc_stack,
        "get_meteorological_boundary": project_meteorology,
        "get_population_receptors": project_population,
        "calculate_exposure_metrics": project_exposure,
        "assess_facilities": project_assessment,
    },
)
