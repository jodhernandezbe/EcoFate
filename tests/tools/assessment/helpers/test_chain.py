"""Tests for running the chain over many facilities: refine, then the full chain."""

from __future__ import annotations

import contextvars

import pytest

from tests.tools.assessment.factories import (
    PEOPLE,
    SETTINGS,
    TOXICITY,
    WEATHER,
    FakeSteps,
    hq_of,
    record,
    stack,
)
from tools.assessment.helpers.chain import (
    assess_all,
    cell,
    in_pool,
    refine_all,
    refine_one,
    worst_case_only,
)
from tools.assessment.helpers.steps import Steps

MARK: contextvars.ContextVar[str | None] = contextvars.ContextVar("MARK", default=None)


def test_refining_chooses_stacks_and_needs_no_site_weather_or_residents() -> None:
    fake = FakeSteps(nei_stacks={"F1": [stack(10), stack(20)]})
    rec = record(eis_ids=["1"], emission_rate=2.5)
    item = refine_one(rec, {"hq": 1.0, "cancer_risk": None}, TOXICITY, fake.steps(), SETTINGS)
    assert item.choice.tier == "NEI" and item.bound == {"hq": 1.0, "cancer_risk": None}
    assert item.worst.hq == pytest.approx(hq_of(2.5, 10.0, 300.0))
    assert not any(name in {"weather", "people"} for name, _ in fake.calls)


def test_the_full_chain_reuses_the_stacks_and_shares_weather_within_a_grid_cell() -> None:
    fake = FakeSteps(nei_stacks={f: [stack(10)] for f in ("A", "B", "C")})
    records = [
        record("A", eis_ids=["1"], latitude=30.01, longitude=-95.0),
        record("B", eis_ids=["1"], latitude=30.02, longitude=-95.0),  # same 0.25-degree cell
        record("C", eis_ids=["1"], latitude=31.0, longitude=-95.0),
    ]
    refined = refine_all([(r, None) for r in records], TOXICITY, fake.steps(), SETTINGS)
    fake.calls.clear()
    items = assess_all(refined, TOXICITY, 2.0, fake.steps(), SETTINGS)
    assert [i["record"]["frs_id"] for i in items] == ["A", "B", "C"]
    assert sum(name == "weather" for name, _ in fake.calls) == 2
    assert not any(name == "nei" for name, _ in fake.calls)  # stacks reused
    assert all(i["level"] == "full" and i["meteorology"] == WEATHER for i in items)
    assert all(i["population"] == PEOPLE and i["radius_km"] == 2.0 for i in items)
    assert ("exposure", (1.0, 1, WEATHER["ambient_temperature"])) in fake.calls


def test_cells_follow_the_grid_and_the_year() -> None:
    a = record(latitude=30.12, longitude=-95.0, reporting_year=2022)
    b = record(latitude=30.13, longitude=-95.0, reporting_year=2022)
    assert cell(a, 0.25) != cell(b, 0.25)  # 30.12 rounds to 30.0, 30.13 to 30.25
    assert cell(a, 0.25) != cell({**a, "reporting_year": 2023}, 0.25)


def test_worst_case_only_keeps_the_worst_case_without_weather_or_residents() -> None:
    fake = FakeSteps(nei_stacks={"F1": [stack(10)]})
    refined = refine_one(record(eis_ids=["1"]), None, TOXICITY, fake.steps(), SETTINGS)
    item = worst_case_only(refined, None)
    assert item["level"] == "worst case only"
    assert item["meteorology"] is None and item["population"] is None
    assert item["exposure"] == refined.worst.exposure


def test_the_callers_context_reaches_every_facility() -> None:
    seen: list[str | None] = []
    fake = FakeSteps()
    base = fake.steps()

    def people(lat: float, lon: float, km: float | None):  # noqa: ANN202
        seen.append(MARK.get())
        return base.people(lat, lon, km)

    steps = Steps(base.nei, base.industry, base.scc, base.pstk, base.weather, people, base.exposure)
    token = MARK.set("this run's key")
    try:
        refined = refine_all([(record(f), None) for f in "ABC"], TOXICITY, steps, SETTINGS)
        assess_all(refined, TOXICITY, None, steps, SETTINGS)
    finally:
        MARK.reset(token)
    assert seen == ["this run's key"] * 3


def test_no_facilities_is_no_work() -> None:
    assert assess_all([], TOXICITY, None, FakeSteps().steps(), SETTINGS) == []
    assert in_pool(str, [], 4) == []


def test_a_setup_error_is_raised() -> None:
    def boom(_: int) -> int:
        raise RuntimeError("misconfigured")

    with pytest.raises(RuntimeError, match="misconfigured"):
        in_pool(boom, [1, 2], 2)


def test_worst_case_only_facility_still_has_a_worker_result_and_profile() -> None:
    refined = refine_one(
        record("A"),
        None,
        TOXICITY,
        FakeSteps(nei_stacks={"A": [stack(10.0)]}).steps(),
        SETTINGS,
    )
    item = worst_case_only(refined, None)
    assert item["level"] == "worst case only"
    assert item["occupational_exposure"]["risk_tier"] is None  # no workplace information given
    assert "not given" in " ".join(item["occupational_exposure"]["warnings"])
    assert item["operational_profile"]["annual_operating_hours"] == 8760.0
