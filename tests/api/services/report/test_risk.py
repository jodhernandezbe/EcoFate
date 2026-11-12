"""Tests for section 6 (risk characterization)."""

from __future__ import annotations

from api.schemas.workspace import Screening, WorkspaceState
from api.services.report.document import new_document
from api.services.report.risk import write_risk
from tests.api.services.report.fixtures import assessed, chemical_only, context, facility, lines


def test_thresholds_and_risk_ranges() -> None:
    doc = new_document()
    write_risk(doc, assessed(), context())
    text = lines(doc)
    assert text[0].startswith(
        "Screening priority bands, not findings. Hazard quotient: low below 0.1",
    )
    assert "high from 1. " in text[0] and "high from 1 × 10⁻⁴" in text[0]
    assert "exceeds" not in text[0] and "threshold of concern" not in text[0]
    assert (
        "Plant A (FRS 110000000001) | 0.375 | 2.5 × 10⁻⁵ | not reported | not reported | Moderate"
        in text
    )
    assert "Plant A (FRS 110000000001) | Fully assessed | 0.375 | 2.5 × 10⁻⁵ | " in text


def test_risk_by_life_cycle_stage_and_condition_of_use_comes_first() -> None:
    doc = new_document()
    write_risk(doc, assessed(), context())
    text = lines(doc)
    by_use = text.index("Risk by life cycle stage and condition of use")
    assert by_use < text.index("Risk by facility")
    assert text[by_use + 2].startswith("Life cycle stage | Condition of use | TRI activity")
    assert text[by_use + 3] == (
        "Manufacturing | Domestic manufacturing | Produce | Plant A (FRS 110000000001) | "
        "0.375 | 2.5 × 10⁻⁵ | Moderate"
    )


def test_conditions_of_use_sorted_by_stage_and_unknown_last() -> None:
    doc = new_document()
    plant = facility()
    cou = plant.conditions_of_use[0]
    processing = cou.model_copy(update={"lifecycle_stage": "Processing", "cou_category": "P"})
    later = facility("110000000002").model_copy(update={"conditions_of_use": [processing, cou]})
    bare = facility("110000000003").model_copy(
        update={"conditions_of_use": [], "conditions_note": "no activity reported"},
    )
    write_risk(doc, WorkspaceState(facilities=[bare, later, plant]), context())
    text = lines(doc)
    start = text.index(
        "Life cycle stage | Condition of use | TRI activity | Facility | "
        "Hazard quotient, worst case | Cancer risk, worst case | Status",
    )
    rows = [t.split(" | ")[:2] for t in text[start + 1 : start + 5]]
    assert rows == [
        ["Manufacturing", "Domestic manufacturing"],
        ["Manufacturing", "Domestic manufacturing"],
        ["Processing", "P"],
        ["not reported", "no activity reported"],
    ]


def test_screened_out_reason() -> None:
    doc = new_document()
    screened = Screening(outcome="screened_out_at_bound", value_hq=0.5, reason="below both")
    plant = facility().model_copy(update={"exposure": None, "status": None, "screening": screened})
    write_risk(doc, WorkspaceState(facilities=[plant]), context())
    text = lines(doc)
    assert any(
        "Screened out at the conservative bound | 0.5 | not reported | below both" in t
        for t in text
    )
    assert any(
        t.endswith("| not reported | not reported | not reported | not reported | not reported")
        for t in text
    )


def test_no_facility_gives_the_empty_sentence() -> None:
    doc, ctx = new_document(), context()
    write_risk(doc, chemical_only(), ctx)
    assert lines(doc) == [ctx.settings.empty_section]
