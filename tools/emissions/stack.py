"""Stack parameter lookup tools: tier 1 (NEI, by facility) and tier 2 (PSTK, by SCC)."""

from __future__ import annotations

import httpx
from langchain_core.tools import tool

from config.efservice import get_efservice_settings, get_frs_settings
from config.loader import get_unit_settings
from config.stack import get_stack_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.stack.nei_lookup import nei_stack_result
from tools.emissions.helpers.stack.pstk import scc_stack_parameters
from tools.schemas import NeiStackResult, StackParameters


def _open_client() -> httpx.Client:
    """Create the HTTP client (the edge where the default collaborator is built)."""
    return httpx.Client()


@tool
def fetch_stack_parameters_from_nei(
    frs_id: str | int,
    eis_ids: list[str] | None = None,
) -> NeiStackResult:
    """Fetch a facility's own stacks (height, diameter, exit velocity and temperature) from the NEI.

    Purpose:
        Plume rise and dispersion depend on stack geometry. This is the first choice for
        stack parameters: call it after identifying a facility, with the `eis_ids` the
        emissions inventory listed for it (when that list is empty the facility has no NEI
        stacks; the inventory's `eis_note` says why). A facility usually has
        several stacks, so it returns several distinct CANDIDATE stacks (real records,
        never averaged), lowest stack first, at most a configured number.
        Pass ALL candidates together, exactly as returned, as the `stacks` of one
        `calculate_exposure_metrics` call (never a subset, never one call per stack); it
        evaluates each and returns the range, then report the range of results rather than
        picking one. When
        `total_candidates` exceeds the number returned, taller stacks were omitted; the
        `warnings` say so and that belongs in the report. If `candidates` is empty (the
        facility has no NEI stack data), call `fetch_stack_parameters_from_scc` instead.

    Args:
        frs_id: EPA Facility Registry Service identifier of the facility (12 digits, as
            returned by `query_emissions_inventory`); a number is also accepted.
        eis_ids: The facility's `eis_ids` from `query_emissions_inventory`, exactly as
            listed. Given, they are used as they are (no lookup); omitted, the FRS registry is
            asked for them.

    Returns:
        A dict with:
        - eis_ids: NEI (EIS) facility IDs found for the FRS ID
        - candidates: list of dicts, each with stack_height (m above ground),
          stack_diameter (m), exit_velocity (m/s), exit_temperature (K), source "NEI" and
          scc null; empty if the NEI has nothing usable
        - total_candidates: distinct combinations found before the cap
        - warnings: why candidates are missing, or what was merged or left out
    """
    with _open_client() as http:
        return nei_stack_result(
            frs_id,
            EfserviceClient(get_efservice_settings(), http),
            get_frs_settings(),
            get_stack_settings(),
            get_unit_settings().aliases,
            eis_ids,
        )


@tool
def fetch_stack_parameters_from_scc(scc_code: str | int | None = None) -> StackParameters:
    """Fetch generic default stack parameters for a process type (SCC); tier 2 fallback.

    Purpose:
        Use this ONLY after `fetch_stack_parameters_from_nei` returned no values (all four
        null) for the facility. The values are EPA PSTK (Point Source Stack Replacements)
        defaults for the kind of process identified by the SCC, not measurements of the
        facility's own stack. If no SCC is given, or the SCC is unknown or invalid, the EPA
        AirToxScreen global point-source default is returned instead (3.0 m height, 0.2 m
        diameter, 4.0 m/s, 295.4 K), so a result always has values. Get the SCC from
        `lookup_scc_process_description`; if it gives none, call this tool without
        `scc_code` to get the global default.

    Args:
        scc_code: Source Classification Code, digits only, e.g. "30600101", exactly as
            returned by `lookup_scc_process_description` (a number is also accepted). Omit it
            (or pass null) when the facility's SCC is not known.

    Returns:
        A dict with:
        - stack_height: m above ground
        - stack_diameter: m
        - exit_velocity: m/s
        - exit_temperature: K
        - source: "PSTK" (SCC-specific default) or "AirToxScreen global default" (generic
          fallback; state this to the user, as it is the least specific estimate)
        - scc: the SCC whose PSTK row was used, or null for the global default
        - warnings: why the global default was used (including "no SCC was given"), or
          notes on the PSTK row chosen
    """
    return scc_stack_parameters(scc_code, get_stack_settings(), get_unit_settings().aliases)
