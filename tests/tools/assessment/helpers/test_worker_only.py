"""Tests for the fugitive-only facilities: a worker result, no community result."""

from __future__ import annotations

import pytest

from config.occupational import get_occupational_settings
from tests.tools.emissions.records import worker_only_facility
from tools.assessment.helpers import worker_only as module
from tools.assessment.helpers.occupational import Workplace, no_limits, unavailable
from tools.assessment.helpers.occupational.dosimetry import empty_case
from tools.assessment.helpers.worker_only import (
    COMMUNITY_REASON,
    assess_worker_only,
    highest,
    sentence,
)
from tools.schemas import Band, EmissionRecord, OccupationalExposure, Toxicity, WorkerOnlyFacility

TOXICITY = Toxicity(rfc=1.0, iur=None)
WORKPLACE = Workplace(
    get_occupational_settings(),
    no_limits("synthetic"),
    "50-00-0",
    None,
    None,
    None,
    None,
)


def _worker(tier: Band | None, twa: float | None) -> OccupationalExposure:
    worst = {**empty_case(), "twa_mg_m3": twa}
    return {**unavailable("synthetic"), "risk_tier": tier, "worst_case": worst}  # type: ignore[typeddict-item]


@pytest.fixture
def values(monkeypatch: pytest.MonkeyPatch) -> dict[str, OccupationalExposure]:
    """Worker values by FRS ID, served by a fake of the worker screening."""
    given: dict[str, OccupationalExposure] = {}

    def fake(record: EmissionRecord, *_: object) -> OccupationalExposure:
        return given[record["frs_id"]]

    monkeypatch.setattr(module, "occupational_exposure", fake)
    return given


def _facilities(*ids: str) -> list[WorkerOnlyFacility]:
    return [worker_only_facility(i, 10.0) for i in ids]


def test_each_facility_gets_a_profile_a_worker_result_and_the_community_reason() -> None:
    (item,) = assess_worker_only(_facilities("W1"), TOXICITY, WORKPLACE)
    assert item["facility"]["frs_id"] == "W1"
    assert item["community_reason"] == COMMUNITY_REASON == "the facility reports no stack release"
    assert item["operational_profile"]["operating_days_per_year"] is not None
    assert item["occupational_exposure"]["fugitive_release_kg_per_year"] == 10.0


def test_the_result_has_no_community_part() -> None:
    (item,) = assess_worker_only(_facilities("W1"), TOXICITY, WORKPLACE)
    assert set(item) == {
        "facility",
        "operational_profile",
        "occupational_exposure",
        "community_reason",
    }


def test_the_highest_worker_band_comes_first_then_the_worst_case_average(
    values: dict[str, OccupationalExposure],
) -> None:
    values.update(
        A=_worker("moderate", 9.0),
        B=_worker("high", 1.0),
        C=_worker("high", 3.0),
        D=_worker(None, None),
        E=_worker("low", 100.0),
    )
    found = assess_worker_only(_facilities("A", "B", "C", "D", "E"), TOXICITY, WORKPLACE)
    assert [i["facility"]["frs_id"] for i in found] == ["C", "B", "A", "E", "D"]
    top = highest(found)
    assert top is not None and top["frs_id"] == "C" and top["worker_risk_tier"] == "high"
    assert top["worker_twa_worst_mg_m3"] == 3.0


def test_nothing_computed_is_never_the_highest_over_a_computed_value(
    values: dict[str, OccupationalExposure],
) -> None:
    values.update(A=_worker(None, None), B=_worker("low", 0.0))
    top = highest(assess_worker_only(_facilities("A", "B"), TOXICITY, WORKPLACE))
    assert top is not None and top["frs_id"] == "B"


def test_without_facilities_there_is_no_highest_and_no_sentence() -> None:
    assert highest([]) is None
    assert sentence(0, 0, None) is None


def test_the_sentence_gives_the_count_names_the_highest_and_the_left_out(
    values: dict[str, OccupationalExposure],
) -> None:
    values.update(A=_worker("low", 1.0), B=_worker("high", 2.0))
    top = highest(assess_worker_only(_facilities("A", "B"), TOXICITY, WORKPLACE))
    text = sentence(2, 4, top)
    assert text is not None
    assert "2 facilities report only a fugitive air release" in text
    assert "B" in text and "worker band: high" in text and "4 more were left out" in text
    assert "left out" not in (sentence(2, 0, top) or "")
    assert "1 facility reports" in (sentence(1, 0, top) or "")
