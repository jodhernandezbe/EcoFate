"""The agent decides from tool descriptions, so each must carry its own decision guidance.

The system prompt names no tool; these tests pin the phrases that make each description
sufficient on its own (when it applies, what a null or a label means, what to do instead).
"""

from __future__ import annotations

import pytest

from tools.registry import get_all_tools

DESCRIPTIONS = {t.name: " ".join(t.description.split()) for t in get_all_tools()}

REQUIRED = {
    "fetch_facility_industry": (
        "the numeric code alone is useless there",
        "only when that title is null",
        "which unit emits",
        "`doc_ctrl_num`",
        '"assigned" when EPA assigned it',
        "a null result is not an error",
        "do not guess it",
        "naics_title",
        "without a code to get the EPA global default",
    ),
    "fetch_chemical_properties": (
        "toxicity benchmarks",
        "null means no usable value",
        "must be reported, not replaced by a guess",
        "`preferred_name` is the only name to call the chemical by",
        "never supply a name for it",
        "Never a number recalled from a chemical's name",
    ),
    "find_tri_category": (
        "not listed in TRI on its own",
        "its releases cover every member of the category together",
        "no similarity is involved",
        "An empty `categories` means",
    ),
    "find_tri_read_across_surrogate": (
        "has no inhalation benchmark",
        "member of a TRI category",
        "report `hybrid_read_across_score` and `within_applicability_domain`",
        "never identifies a chemical from its name",
        "a read-across estimate, not a measured value",
        "outside the applicability domain",
        "It is reported, never applied",
        "A null surrogate means none could be found",
        "Never a number recalled from a chemical's name",
    ),
    "query_emissions_inventory": (
        "every facility found (listed or",
        "eis_ids",
        "nothing about its process",
        "not evidence that nobody emits it",
        "Never a number recalled from a chemical's name",
        "location",
    ),
    "lookup_scc_process_description": (
        "not an official NAICS-to-SCC crosswalk",
        "judge them",
        "empty `matches` list",
        "in WORDS",
        "Never pass only the numeric NAICS code",
        "refused with a warning",
        "without `scc_code` to get the EPA global default stack",
    ),
    "fetch_stack_parameters_from_nei": (
        "first choice",
        "ALL candidates together",
        "never a subset",
        "taller stacks were omitted",
        "report the range",
        "call `fetch_stack_parameters_from_scc` instead",
    ),
    "fetch_stack_parameters_from_scc": (
        "ONLY after `fetch_stack_parameters_from_nei` returned no values",
        "not measurements of the facility's own stack",
        "without `scc_code`",
        "AirToxScreen global default",
    ),
    "get_meteorological_boundary": (
        "annual representatives, not worst-case",
        "screening default",
        "say so to the user",
        "10 m, not at stack height",
    ),
    "get_population_receptors": (
        "residents (not workers or visitors)",
        "screening default",
        "say so to the user",
        "United States only",
    ),
    "assess_facilities": (
        "Use this to assess the facilities of a chemical",
        "not only the largest emitters",
        "is screened out",
        "Report every facility in `facilities` in the results table and every one in",
        "not a sample",
        "state the screening counts, thresholds and `note`",
        "Give `frs_ids` only when the user asks about particular",
        '"AirToxScreen global default"',
        "say so",
        "Never a number recalled from a chemical's name",
        "screening estimates, not regulatory determinations",
    ),
    "check_job_status": (
        "It never starts or changes a job",
        "has been started, not finished",
        "never state or guess its results",
        "do not describe them before then",
    ),
    "calculate_exposure_metrics": (
        "`stack_source` echoes where the stack came from",
        "can be far higher than for the facility's real stack",
        "ALL of a facility's candidate stacks",
        "never a subset, never one call per stack",
        "report the `range`",
        "A null number means it could not be computed",
        "must be reported, not filled in",
        "may fall where nobody lives",
    ),
}


def test_every_registered_tool_is_audited() -> None:
    assert set(REQUIRED) == set(DESCRIPTIONS)


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_description_carries_its_decision_guidance(name: str) -> None:
    missing = [phrase for phrase in REQUIRED[name] if phrase not in DESCRIPTIONS[name]]
    assert missing == []


@pytest.mark.parametrize("name", sorted(DESCRIPTIONS))
def test_no_description_orders_the_workflow(name: str) -> None:
    """A tool says when it applies; it does not claim a position in a fixed sequence."""
    text = DESCRIPTIONS[name].lower()
    assert "use this first" not in text
    assert "final step" not in text
    assert "first step" not in text
