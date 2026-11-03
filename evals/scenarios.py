"""Scenario catalogue: query, deterministic checks, judges, and why a scenario is blocked."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from evals import checks as c
from evals.judges import ASKS_FOR_CAS, CATEGORY_MATCH_DISCLOSED, COMPLETE_ASSESSMENT_REPORT, Judge


@dataclass(frozen=True)
class ExtraCall:
    """A tool call made once when recording, to cover a route the agent may take."""

    tool: str
    args: Mapping[str, object]


@dataclass(frozen=True)
class Scenario:
    """One evaluation scenario; its cassette is ``<cassette_dir>/<id>.json``."""

    id: str
    query: str
    checks: tuple[c.Check, ...] = ()
    judges: tuple[Judge, ...] = ()
    blocked: str | None = None
    extra_calls: tuple[ExtraCall, ...] = ()


_NOT_WRITTEN = "checks and cassette not written yet"

CHEMICAL_NAME_ONLY = Scenario(
    id="chemical-name-only",
    query="Run a screening exposure and risk assessment for formaldehyde air releases.",
    checks=(c.completed(), c.no_tool_called()),
    judges=(ASKS_FOR_CAS,),
)

# 1,2-Dibromo-3-chloropropane: its live TRI inventory has two facilities, both with NEI stacks,
# which keeps the run and the cassette small. The checks are about the outcome, whichever
# route the agent takes (the batch assessment, or the chain by hand): every facility assessed
# and reported, and the chain done right when it is driven by hand.
FULL_ASSESSMENT_CAS = "96-12-8"

FULL_ASSESSMENT = Scenario(
    id="full-assessment-with-nei-stacks",
    query=(
        "Assess the inhalation exposure and health risk from air releases of "
        f"CAS {FULL_ASSESSMENT_CAS}."
    ),
    checks=(
        c.completed(),
        c.no_unrecorded(),
        c.called_with("fetch_chemical_properties", cas_number=FULL_ASSESSMENT_CAS),
        c.every_facility_covered(),
        c.every_covered_facility_reported(),
        c.report_names_each_source(),
        c.site_inputs_per_assessed_facility(),
        c.exposure_covers_every_candidate(),
        c.no_fallback_for_facilities_with_candidates(),
    ),
    judges=(COMPLETE_ASSESSMENT_REPORT,),
    # The agent may assess the facilities by the batch tool instead of by hand; record it too.
    # It may also look the chemical up in the read-across tool first, and ask for the weather at a
    # facility, with and without a reporting year (the same sites as the recorded calls).
    extra_calls=(
        ExtraCall(c.ASSESSMENT, {"cas_number": FULL_ASSESSMENT_CAS}),
        ExtraCall("find_tri_read_across_surrogate", {"cas_number": FULL_ASSESSMENT_CAS}),
        ExtraCall("get_meteorological_boundary", {"latitude": "33.2044", "longitude": "-92.6308"}),
        ExtraCall(
            "get_meteorological_boundary",
            {"latitude": "40.631622", "longitude": "-80.54632"},
        ),
        ExtraCall(
            "get_meteorological_boundary",
            {"latitude": "33.2044", "longitude": "-92.6308", "reporting_year": "2024"},
        ),
        ExtraCall(
            "get_meteorological_boundary",
            {"latitude": "40.631622", "longitude": "-80.54632", "reporting_year": "2024"},
        ),
    ),
)

# 2-Chlorophenol is not a discrete TRI chemical; TRI reports it under the chlorophenols
# category (N084). The agent must find that category before seeking an analogue, say so, and say
# the releases cover the whole category. Its cassette: `uv run python -m evals record
# category-member-chlorophenol`.
CATEGORY_MEMBER_CAS = "95-57-8"

CATEGORY_MEMBER = Scenario(
    id="category-member-chlorophenol",
    query=(
        "Assess the inhalation exposure and health risk from air releases of "
        f"CAS {CATEGORY_MEMBER_CAS}."
    ),
    checks=(
        c.completed(),
        c.called_with("find_tri_category", cas_number=CATEGORY_MEMBER_CAS),
        c.called_with("query_emissions_inventory", cas_number="N084"),
    ),
    judges=(CATEGORY_MATCH_DISCLOSED,),
)


# Acrolein (107-02-8): CompTox has an RfC but no inhalation unit risk, so a cancer-risk result
# cannot be concluded. The agent must stop and ask for the IUR, not compute a risk without it.
ACROLEIN_CAS = "107-02-8"

MISSING_BENCHMARK = Scenario(
    id="missing-benchmark-asks",
    query=(
        f"Assess the inhalation exposure and cancer risk from air releases of CAS {ACROLEIN_CAS}."
    ),
    checks=(
        c.completed(),
        c.no_unrecorded(),
        c.called_with(c.PROPERTIES, cas_number=ACROLEIN_CAS),
        c.not_called(c.EXPOSURE),
        c.asks_for_missing("iur"),
    ),
)

CATALOGUE: tuple[Scenario, ...] = (
    CHEMICAL_NAME_ONLY,
    MISSING_BENCHMARK,
    FULL_ASSESSMENT,
    CATEGORY_MEMBER,
    Scenario("nei-empty-process-fallback", "", blocked=_NOT_WRITTEN),
    Scenario("unknown-industry-global-default", "", blocked=_NOT_WRITTEN),
    Scenario("scc-search-empty", "", blocked=_NOT_WRITTEN),
    Scenario("nationwide-many-facilities", "", blocked=_NOT_WRITTEN),
    Scenario("null-toxicity-value", "", blocked=_NOT_WRITTEN),
    Scenario("territory-population-default", "", blocked=_NOT_WRITTEN),
    Scenario("unknown-cas", "", blocked=_NOT_WRITTEN),
    Scenario("out-of-scope-request", "", blocked=_NOT_WRITTEN),
    Scenario("tri-unreachable", "", blocked="needs the TRI-unreachable warning fix"),
    Scenario("weather-year", "", blocked="needs the meteorology year fallback fix"),
)


def scenario(scenario_id: str) -> Scenario:
    """Return the catalogue scenario ``scenario_id``; raises ``KeyError`` if unknown."""
    for item in CATALOGUE:
        if item.id == scenario_id:
            return item
    raise KeyError(f"unknown scenario: {scenario_id}")
