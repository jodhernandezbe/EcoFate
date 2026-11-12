"""Tests for the workers of the screened-out facilities: screened all the same."""

from __future__ import annotations

import pytest

from config.occupational import get_occupational_settings
from tests.tools.emissions.records import emission_record
from tools.assessment.helpers import screened_workers as module
from tools.assessment.helpers.occupational import Workplace, no_limits, unavailable
from tools.assessment.helpers.occupational.dosimetry import empty_case
from tools.assessment.helpers.screened_workers import (
    highest_worker,
    sentence,
    with_workers,
    worker_bands,
)
from tools.schemas import Band, EmissionRecord, OccupationalExposure, ScreenedOut, Toxicity

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


def _out(frs_id: str) -> ScreenedOut:
    return ScreenedOut(
        record=emission_record(frs_id, 0.01),
        stage="bound",
        hq=0.01,
        cancer_risk=None,
        stacks=[],
        stack_tier="AirToxScreen global default",
        reason="synthetic",
    )


@pytest.fixture
def values(monkeypatch: pytest.MonkeyPatch) -> dict[str, OccupationalExposure]:
    """Worker values by FRS ID, served by a fake of the worker screening."""
    given: dict[str, OccupationalExposure] = {}

    def fake(record: EmissionRecord, *_: object) -> OccupationalExposure:
        return given[record["frs_id"]]

    monkeypatch.setattr(module, "occupational_exposure", fake)
    return given


def test_each_screened_out_facility_gets_a_profile_and_a_worker_result() -> None:
    (item,) = with_workers([_out("S1")], TOXICITY, WORKPLACE)
    assert item["record"]["frs_id"] == "S1" and item["stage"] == "bound"
    assert "occupational_exposure" in item and "operational_profile" in item
    assert item["occupational_exposure"]["rfc"] == 1.0


def test_the_community_fields_are_kept_as_they_were() -> None:
    given = _out("S1")
    (item,) = with_workers([given], TOXICITY, WORKPLACE)
    assert {k: item[k] for k in given} == given  # type: ignore[literal-required]


def test_the_bands_are_counted_and_the_highest_worker_value_is_named(
    values: dict[str, OccupationalExposure],
) -> None:
    values.update(A=_worker("moderate", 9.0), B=_worker("high", 1.0), C=_worker(None, None))
    out = with_workers([_out("A"), _out("B"), _out("C")], TOXICITY, WORKPLACE)
    assert worker_bands(out) == {"moderate": 1, "high": 1, "not computed": 1}
    top = highest_worker(out)
    assert top is not None and top["frs_id"] == "B" and top["worker_risk_tier"] == "high"
    assert top["worker_twa_worst_mg_m3"] == 1.0
    text = sentence(out)
    assert text is not None
    assert "1 high, 1 moderate, 1 not computed" in text and "(B, worker band: high)" in text


def test_nothing_screened_out_gives_no_summary() -> None:
    assert worker_bands([]) == {}
    assert highest_worker([]) is None and sentence([]) is None


def test_an_item_without_a_worker_result_is_counted_as_not_computed_and_never_ranked() -> None:
    assert worker_bands([_out("OLD")]) == {"not computed": 1}
    assert highest_worker([_out("OLD")]) is None
