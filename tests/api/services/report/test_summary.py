"""Tests for section 1 (summary of findings)."""

from __future__ import annotations

from api.schemas.workspace import RiskSummary, WorkspaceState
from api.services.report.document import new_document
from api.services.report.summary import write_summary
from tests.api.services.report.fixtures import assessed, context, lines


def test_highest_risks_with_facility_stack_and_status() -> None:
    doc = new_document()
    write_summary(doc, assessed(), context())
    text = lines(doc)
    assert "Facilities in this assessment: 1." in text[0]
    assert "Worst-case hazard quotient | 0.375 | Moderate | Plant A (FRS 110000000001) | 1" in text
    assert (
        "Worst-case lifetime cancer risk | 2.5 × 10⁻⁵ | Moderate | Plant A (FRS 110000000001) | 1"
        in text
    )


def test_names_life_cycle_stages_and_conditions_of_use() -> None:
    doc = new_document()
    state = assessed()
    plant = state.facilities[0]
    staged = plant.model_copy(update={"lifecycle_stages": ["Use", "Manufacturing"]})
    write_summary(doc, state.model_copy(update={"facilities": [plant, staged]}), context())
    assert lines(doc)[1] == (
        "Life cycle stages: Manufacturing; Use. "
        "Conditions of use: Domestic manufacturing (Manufacturing)."
    )


def test_absent_conditions_of_use_read_not_reported() -> None:
    doc = new_document()
    plant = assessed().facilities[0].model_copy(update={"conditions_of_use": []})
    write_summary(doc, WorkspaceState(facilities=[plant]), context())
    assert lines(doc)[1] == "Life cycle stages: not reported. Conditions of use: not reported."


def test_absent_risk_prints_reason_never_zero() -> None:
    doc = new_document()
    state = WorkspaceState(risk=RiskSummary(reason="not yet computed"))
    write_summary(doc, state, context())
    text = lines(doc)
    assert "Representative hazard quotient | not reported (not yet computed) |  |  | " in text
    assert not any(" | 0 |" in line for line in text)
