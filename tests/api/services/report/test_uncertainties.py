"""Tests for section 7 (uncertainties and limitations)."""

from __future__ import annotations

from api.schemas.workspace import WorkspaceState
from api.services.report.document import new_document
from api.services.report.uncertainties import warning_groups, write_uncertainties
from tests.api.services.report.fixtures import assessed, context, facility, lines


def test_warnings_grouped_with_defaults_and_unattributed() -> None:
    groups = dict(warning_groups(assessed()))
    assert groups["Workspace"] == ["a result was left out"]
    assert groups["Chemical"] == ["IUR missing", "read-across note"]
    assert groups["Plant A (FRS 110000000001)"] == [
        "stack note",
        "Meteorology is a screening default (Source W).",
    ]
    assert groups["Unattributed results"] == ["some_tool: two facilities matched"]


def test_weather_of_no_facility_is_listed() -> None:
    plant = facility()
    assert plant.meteorology is not None
    loose = plant.meteorology.model_copy(update={"frs_id": None})
    groups = dict(warning_groups(WorkspaceState(meteorology=loose)))
    assert groups["Meteorology not attached to a facility"] == [
        "Meteorology is a screening default (Source W).",
    ]


def test_nothing_to_report_gives_the_empty_sentence() -> None:
    doc, ctx = new_document(), context()
    write_uncertainties(doc, WorkspaceState(facilities=[facility(defaults=False)]), ctx)
    assert lines(doc) == ["Plant A (FRS 110000000001)", "stack note"]
    doc = new_document()
    write_uncertainties(doc, WorkspaceState(), ctx)
    assert lines(doc) == [ctx.settings.empty_section]
