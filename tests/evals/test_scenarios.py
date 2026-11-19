"""The scenario catalogue records the batch route beside the by-hand one."""

from __future__ import annotations

from evals.checks import ASSESSMENT
from evals.scenarios import (
    ACROLEIN_CAS,
    BACKGROUND_ASSESSMENT,
    CATALOGUE,
    FULL_ASSESSMENT,
    FULL_ASSESSMENT_CAS,
    MISSING_BENCHMARK,
)


def test_full_assessment_also_records_the_batch_route() -> None:
    extras = [(e.tool, dict(e.args)) for e in FULL_ASSESSMENT.extra_calls]
    assert extras[0] == (ASSESSMENT, {"cas_number": FULL_ASSESSMENT_CAS})


def test_full_assessment_also_records_the_variations_the_agent_takes() -> None:
    extras = [(e.tool, dict(e.args)) for e in FULL_ASSESSMENT.extra_calls]
    assert ("find_tri_read_across_surrogate", {"cas_number": FULL_ASSESSMENT_CAS}) in extras
    weather = [args for tool, args in extras if tool == "get_meteorological_boundary"]
    assert len(weather) == 4
    assert sum("reporting_year" in args for args in weather) == 2  # each site, with and without


def test_missing_benchmark_also_records_the_surrogate_search() -> None:
    extras = [(e.tool, dict(e.args)) for e in MISSING_BENCHMARK.extra_calls]
    assert extras == [
        (
            "find_tri_read_across_surrogate",
            {"cas_number": ACROLEIN_CAS, "require_toxicity_benchmarks": True},
        ),
        ("find_tri_read_across_surrogate", {"cas_number": ACROLEIN_CAS}),
    ]


def test_scenarios_without_extra_calls_record_none() -> None:
    others = [
        s for s in CATALOGUE if s not in (FULL_ASSESSMENT, MISSING_BENCHMARK, BACKGROUND_ASSESSMENT)
    ]
    assert all(s.extra_calls == () for s in others)


def test_background_assessment_has_its_own_cassette() -> None:
    from evals.scenarios import BACKGROUND_ASSESSMENT, BACKGROUND_CAS
    from evals.suite import cassette_path

    assert BACKGROUND_ASSESSMENT.background
    assert BACKGROUND_CAS in BACKGROUND_ASSESSMENT.query
    assert BACKGROUND_ASSESSMENT.cassette_id is None
    assert cassette_path(BACKGROUND_ASSESSMENT).name == f"{BACKGROUND_ASSESSMENT.id}.json"
