"""Emissions inventory query tool."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from functools import partial

import httpx
from langchain_core.tools import tool

from commons.cas import format_cas
from commons.ttl_cache import TtlCache
from config.assessment import get_assessment_settings
from config.conditions_of_use import get_conditions_settings
from config.efservice import get_efservice_settings
from config.frs_eis import get_frs_eis_settings
from config.frs_point import get_frs_point_settings
from config.industry import get_industry_settings
from config.loader import get_emissions_settings, get_tri_settings, get_unit_settings
from config.plant_hours import get_plant_hours_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.inventory.conditions import ConditionsMapper, get_crosswalk
from tools.emissions.helpers.inventory.eis import UNREACHABLE_NOTE, EisResolver
from tools.emissions.helpers.inventory.frs_point import FrsLocator
from tools.emissions.helpers.inventory.listing import rank_and_cap, with_worker_only
from tools.emissions.helpers.inventory.lookup import TriReadError, lookup_emissions
from tools.emissions.helpers.inventory.plant_hours import PlantHours, get_baseline
from tools.emissions.helpers.inventory.rate import HoursFor, operating_hours_per_year
from tools.emissions.helpers.inventory.tri import TriFetcher
from tools.emissions.helpers.naics_subsectors import subsector_titles, with_subsectors
from tools.emissions.helpers.naics_titles import naics_titles, with_titles
from tools.schemas import EmissionRecord, FacilityRecord, InventoryResult
from tools.tri_categories import get_category_index

logger = logging.getLogger(__name__)
Resolve = Callable[[list[EmissionRecord]], list[EmissionRecord]]


def _current_year() -> int:
    """Return the current calendar year (the edge where the clock is read)."""
    return date.today().year


def _open_client() -> httpx.Client:
    """Create the HTTP client (the edge where the default collaborator is built)."""
    return httpx.Client()


def _eis_resolver(client: httpx.Client) -> Resolve:
    """The bulk EIS ID lookup: the shared request policy on the FRS service's own URL."""
    eis = get_frs_eis_settings()
    service = replace(get_efservice_settings(), base_url=eis.base_url)
    return partial(remembered_eis, EisResolver(EfserviceClient(service, client), eis))


def remembered_eis(resolve: Resolve, records: list[EmissionRecord]) -> list[EmissionRecord]:
    """The records with their EIS IDs, asking FRS only for those not remembered."""
    known = {r["frs_id"]: _EIS.get(r["frs_id"]) for r in records}
    unknown = [r for r in records if known[r["frs_id"]] is None]
    for found in resolve(unknown) if unknown else []:
        entry = (found["eis_ids"], found["eis_note"])
        known[found["frs_id"]] = entry
        if found["eis_note"] != UNREACHABLE_NOTE:
            _EIS.put(found["frs_id"], entry)
    out: list[EmissionRecord] = []
    for record in records:
        ids, note = known[record["frs_id"]] or ([], None)
        out.append({**record, "eis_ids": list(ids), "eis_note": note})
    return out


def _frs_locator(client: httpx.Client) -> FrsLocator:
    """The bulk coordinates lookup: the shared request policy on the FRS service's own URL."""
    frs = get_frs_point_settings()
    service = replace(get_efservice_settings(), base_url=frs.base_url)
    return FrsLocator(EfserviceClient(service, client), frs)


@tool(response_format="content_and_artifact")
def query_emissions_inventory(
    cas_number: str,
    state: str | None = None,
    city: str | None = None,
) -> tuple[InventoryResult, list[EmissionRecord]]:
    """List facilities that reported emitting a chemical, with their latest reported release.

    Purpose:
        Use this to discover emission sources of a chemical from the EPA Toxics Release
        Inventory (TRI). For each facility it uses the most recent year the facility
        reported, so different facilities may be reported for different years. The
        facilities listed are stack (point-source) air sources; water and land releases are
        not returned. A facility that reports a fugitive air release but no stack release
        is not a stack source: it is listed apart in `worker_only` (see Returns). Each
        result carries the facility's location (latitude, longitude,
        address) and its `frs_id` identifies it. A widely reported chemical
        can take a while because TRI is read in many pages (facilities without TRI coordinates
        are then located in FRS, many per request) and may have over a thousand facilities.
        Only the largest are listed to you, highest `emission_rate` first, so the first
        facilities listed are the largest sources; `total_found`, `matching` and `note` say how
        many more there are. Never present a list as complete when `note` says it is partial.
        To look at a place, call again with `state` and/or `city`: the largest facilities there
        are listed. The listing is a view of the largest sources, not the set to assess: a
        small emitter can matter as much as a large one, and every facility found (listed or
        not) stays available to the assessment. TRI gives
        each facility's primary NAICS code and this tool adds its title in words
        (`naics_title`), nothing about its process; a process is only a candidate derived from
        the industry.
        Zero facilities means no stack air release was found for this CAS number (and place) in
        TRI, which is not evidence that nobody emits it: TRI covers only facilities above its
        reporting thresholds. If `note` says TRI could not be read, nothing is known: that is
        not zero releases, so do not report it as one.
        A chemical TRI reports only as a member of a category (see `find_tri_read_across_surrogate`,
        `query_categories`) has its releases under the category code, e.g. "N420": pass that code
        as `cas_number`. Those releases are for the whole category, every member together, never
        for one chemical; the `note` says so, and you must say so too.

    Args:
        cas_number: CAS registry number as the user gave it, e.g. "50-00-0" (hyphens
            optional), or a TRI category code such as "N420" (only one reported by the
            read-across result). Never a number recalled from a chemical's name: if the user
            gave only a name, ask for the CAS number instead of calling this tool.
        state: Optional. Keep only facilities in this state, as its two-letter postal
            abbreviation, e.g. "TX".
        city: Optional. Keep only facilities in this city, by its exact name, e.g. "Houston"
            (a metropolitan area spans several city names; use `state` for a wider look).

    Returns:
        A dict with:
        - total_found: facilities found for this chemical, before `state` and `city`
        - matching: facilities that match `state` and `city` (all of them when none is given)
        - shown: facilities listed in `facilities`
        - note: says that the list is partial and how to see others; null when it is complete
        - worker_only: facilities with a fugitive air release and no stack release, largest
          fugitive release first (at most a configured number; empty if none), each with the
          facility fields below except the stack ones (no `environmental_medium`, `eis_ids`,
          `eis_note`, `total_release`, `unit` or `emission_rate`). They expose their
          workers, not the neighbours: they have no stack release, so they get only a worker
          result in the assessment and no community result; never describe them as stack sources
          or give them an emission rate
        - worker_only_left_out: fugitive-only facilities beyond that number, not listed (say so)
        - facilities: the largest matching facilities, highest `emission_rate` first (empty if
          none, if the CAS number is invalid, or if TRI could not be read), each with:
          - frs_id: EPA Facility Registry Service identifier
          - facility_name: facility display name (may be null)
          - environmental_medium: TRI release medium, e.g. "AIR STACK"
          - reporting_year: latest year the facility reported for that medium (only the last 2
            reporting years are searched, so a facility that stopped reporting earlier is
            absent)
          - doc_ctrl_num: TRI control number of that year's submission (null if TRI gave
            none); `fetch_facility_industry` takes it
          - naics_code: primary NAICS code of that submission, digits only (null if TRI gave
            none)
          - eis_ids: the facility's NEI (EIS) facility IDs, looked up for the facilities
            listed; pass them to `fetch_stack_parameters_from_nei` so it needs no lookup of
            its own. Empty when FRS registers no EIS facility for it: then `eis_note` says
            why, and the NEI has no stack for the facility (go to the SCC-based stack)
          - eis_note: null, or why `eis_ids` is empty, or that the IDs are those of another
            FRS record of the same site (TRI's FRS ID had no EIS registration): report that
            with the stacks
          - naics_subsector, naics_subsector_title: the first three digits of the NAICS code and
            that subsector's title (e.g. 325, Chemical Manufacturing), null when the code has
            fewer than three digits; what facilities are grouped by in the dashboard
          - naics_title: that code's title in words, from the Census code lists (null when
            the code is missing or not a six-digit code of a listed vintage); this is what the
            SCC process search needs. Only when it is null is `fetch_facility_industry`
            worth calling: it asks TRI's own reference table and says whether the facility
            reported the code or EPA assigned it
          - total_release: quantity released in that year, in `unit` per year, as reported
          - unit: unit of `total_release` as reported by TRI, e.g. "Pounds"
          - emission_rate: average emission rate, g/s, assuming the facility operates
            `operating_hours_per_year`
          - operating_hours_per_year: hours per year assumed for `emission_rate`: the
            industry's average plant hours from the Census plant capacity survey when the
            facility's NAICS code (or a shorter prefix of it) is in that survey, otherwise
            8760 (continuous operation, a conservative screening assumption)
          - operating_hours_source: says which of the two it is, and for a survey figure the
            release, the survey's NAICS code and its plant hours per week
          - fugitive_release_kg_per_year: the facility's TRI fugitive air release (evaporation
            and leaks inside or beside the plant, which mainly expose its workers rather than
            the neighbours), kg per year, as `fugitive_reporting_year` reported it; null when
            TRI has none. It is not part of `total_release` or `emission_rate`
          - conditions_of_use: the TSCA conditions of use implied by what the facility told TRI
            it does with the chemical (produces, imports, uses it as a reactant, in a
            formulation, in articles, as a processing aid, ...). A facility can have several; each
            has `tri_activity`, `tri_section` (Form R Section 3 item), `lifecycle_stage`,
            `cou_category` and `mapping_strength` (a "None (CDR exempt)" strength, for an
            impurity, is not a condition of use in the CDR sense)
          - lifecycle_stages: the distinct TSCA life cycle stages of `conditions_of_use`
          - conditions_note: why `conditions_of_use` is empty (null when it is not); an empty list
            with a note means "unknown" or "none reported", not "no use"
          - latitude, longitude: decimal degrees (negative longitude is west); from TRI, or
            from the facility's FRS record when TRI has none
          - address, city, county, state, zip_code: facility location (each may be null)
    """
    try:
        return inventory_listing(cas_number, state, city)
    except TriReadError as exc:
        return _unread(state, city, str(exc))


def _unread(state: str | None, city: str | None, reason: str) -> Listing:
    """An empty view whose note says TRI could not be read, so it is not read as no releases."""
    result, _ = rank_and_cap([], get_tri_settings().max_listed, state, city)
    note = f"{reason}. This is not evidence that there are no releases: retry the query"
    return {**result, "note": note}, []


Listing = tuple[InventoryResult, list[EmissionRecord]]
_LISTINGS: TtlCache[tuple[str, str | None, str | None, int], Listing] = TtlCache(
    get_assessment_settings().inventory_cache_seconds,
)


# FRS ID -> (EIS IDs, note); a lookup FRS could not answer is not remembered.
_EIS: TtlCache[str, tuple[list[str], str | None]] = TtlCache(
    get_frs_eis_settings().cache_seconds,
    max_entries=50_000,
)


def clear_inventory_cache() -> None:
    """Forget every remembered inventory and EIS ID (tests, or a change of configuration)."""
    _LISTINGS.clear()
    _EIS.clear()


def inventory_listing(
    cas_number: str,
    state: str | None = None,
    city: str | None = None,
) -> Listing:
    """The model's view and the complete matching list of a chemical's inventory.

    The same inventory is reused for ``[assessment].inventory_cache_seconds``, so listing the
    facilities and then assessing them reads TRI once. Copies are returned.
    """
    identifier = _identifier(cas_number)
    if identifier is None:
        logger.warning(
            "query_emissions_inventory: %r is not a valid CAS number or TRI category code",
            cas_number,
        )
        return rank_and_cap([], get_tri_settings().max_listed, state, city)
    key = (identifier, state, city, _current_year())
    cached = _LISTINGS.get(key)
    if cached is None:
        cached = _read_listing(identifier, state, city, key[3])
        _LISTINGS.put(key, cached)
    return _with_category_note(identifier, cached)


def _identifier(raw: str) -> str | None:
    """The hyphenated CAS number, or the TRI category code, ``raw`` stands for; else None."""
    cas = format_cas(raw)
    if cas is not None:
        return cas
    code = raw.strip().upper()
    return code if get_category_index().has_code(code) else None


def _with_category_note(identifier: str, listing: Listing) -> Listing:
    """For a category code, say in the note that the releases cover the whole category."""
    name = get_category_index().name_of(identifier)
    if format_cas(identifier) is not None or name is None:
        return listing
    result, records = listing
    note = (
        f"releases are reported for the whole TRI category {identifier} ({name}), "
        "not for one member chemical"
    )
    both = note if result["note"] is None else f"{note}. {result['note']}"
    return {**result, "note": both}, records


def _read_listing(cas: str, state: str | None, city: str | None, year: int) -> Listing:
    """Read TRI (and FRS) for the chemical, then title, rank, cap and resolve the listed."""
    tri = get_tri_settings()
    with _open_client() as client:
        ef = EfserviceClient(get_efservice_settings(), client)
        found = lookup_emissions(
            cas,
            tri,
            get_emissions_settings(),
            get_unit_settings().aliases,
            TriFetcher(tri, ef, year),
            year,
            _frs_locator(client),
            _hours_for(),
            _conditions(),
        )
        eis = _eis_resolver(client)
        result, matching = rank_and_cap(_titled(found.stack), tri.max_listed, state, city, eis)
        worker_only = _titled(found.worker_only)
        return with_worker_only(result, worker_only, tri.max_worker_only, state, city), matching


def _hours_for() -> HoursFor:
    """The resolver of a facility's operating hours: industry baseline, else the default."""
    settings = get_plant_hours_settings()
    default = operating_hours_per_year(get_emissions_settings())
    return PlantHours(get_baseline(settings), settings, default)


def _conditions() -> ConditionsMapper:
    """The mapper from a facility's TRI activities to TSCA conditions of use."""
    settings = get_conditions_settings()
    return ConditionsMapper(get_crosswalk(settings), settings)


def with_eis_ids(records: list[EmissionRecord]) -> list[EmissionRecord]:
    """Copies of ``records`` with their EIS IDs (for facilities beyond the listed ones)."""
    with _open_client() as client:
        return _eis_resolver(client)(records)


def _titled[R: FacilityRecord](records: list[R]) -> list[R]:
    """The records with each NAICS code's title and subsector from the local Census lists."""
    settings = get_industry_settings()
    titled = with_titles(records, naics_titles(settings))
    return with_subsectors(titled, subsector_titles(settings))
