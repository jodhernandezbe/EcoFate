"""Tests for section 5 (exposure assessment)."""

from __future__ import annotations

from api.schemas.workspace import Dose, WorkspaceState
from api.services.report.document import new_document
from api.services.report.exposure import write_exposure
from tests.api.services.report.fixtures import assessed, chemical_only, context, facility, lines


def test_stacks_weather_receptors_and_concentrations() -> None:
    doc = new_document()
    write_exposure(doc, assessed(), context())
    text = lines(doc)
    assert "Plant A (FRS 110000000001)" in text
    assert "1 | 15 m | 1.5 m | 12.5 m/s | 350 K | Tier 1: Empirical NEI | Source S" in text
    assert "Stacks evaluated | 1 of 1" in text
    assert "Worst-case maximum concentration | 7.5 µg/m³" in text
    assert "Representative maximum concentration | not reported" in text
    assert "Meteorology source | Source W (screening default)" in text
    assert "Population within the radius | 12,345" in text


def test_facility_without_stacks_or_results() -> None:
    doc = new_document()
    bare = facility().model_copy(
        update={"stacks": [], "exposure": None, "meteorology": None, "receptors": None},
    )
    write_exposure(doc, WorkspaceState(facilities=[bare]), context())
    text = lines(doc)
    assert "Stack parameters: not reported" in text
    assert "Modelled concentrations | not reported" in text
    assert "Meteorology | not reported" in text
    assert "Receptor population | not reported" in text


def test_no_facility_gives_the_empty_sentence() -> None:
    doc, ctx = new_document(), context()
    write_exposure(doc, chemical_only(), ctx)
    assert lines(doc) == [ctx.settings.empty_section]


def test_dose_by_age_band_and_the_assumptions_behind_it() -> None:
    base = assessed()
    dose = Dose(highest_mg_kg_day=0.5, highest_band="0-4", by_band={"0-4": 0.5, "18-64": 0.25})
    ranges = base.facilities[0].exposure
    assert ranges is not None
    state = base.model_copy(
        update={
            "facilities": [
                base.facilities[0].model_copy(
                    update={"exposure": ranges.model_copy(update={"dose": dose})},
                ),
            ],
        },
    )
    doc = new_document()
    write_exposure(doc, state, context())
    text = lines(doc)
    assert "Average daily dose, age 0-4 (highest) | 0.5 mg/(kg·day)" in text
    assert "Average daily dose, age 18-64 | 0.25 mg/(kg·day)" in text
    assert "Inhalation exposure assumptions" in text
    assert any(line.startswith("Exposure frequency | 350") for line in text)
    assert any(line.startswith("Age 0-4: inhalation rate, body weight") for line in text)


def test_missing_dose_is_not_reported() -> None:
    doc = new_document()
    write_exposure(doc, assessed(), context())
    assert "Inhalation dose by age band | not reported" in lines(doc)
