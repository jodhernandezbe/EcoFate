"""Tests for the assembled report: section order, empty sections and value provenance."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime

from api.schemas.workspace import Chemical, WorkspaceState
from api.services.report.builder import build_report, file_name, has_findings
from config.exposure import get_exposure_settings
from tests.api.services.report.fixtures import (
    assessed,
    chemical_only,
    context,
    headings,
    lines,
    load,
)

WHEN = datetime(2026, 1, 2, 3, 4)
_NUMBER = re.compile(r"\d(?:[\d,.]*\d)?(?: × 10[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)?")


def test_headings_in_configured_order() -> None:
    ctx = context()
    doc = load(build_report(assessed(), "Answer.", ctx, WHEN))
    expected = [f"{n}. {t}" for n, t in enumerate(ctx.settings.headings.ordered(), start=1)]
    assert headings(doc) == expected


def test_chemical_only_keeps_empty_sections() -> None:
    ctx = context()
    text = lines(load(build_report(chemical_only(), None, ctx, WHEN)))
    for title in ("4. Releases", "5. Exposure assessment", "6. Risk characterization"):
        assert text[text.index(title) + 1] == ctx.settings.empty_section
    assert text[-1] == ctx.settings.no_assessor_summary


def _leaves(value: object) -> Iterator[object]:
    if isinstance(value, dict):
        for item in value.values():  # pyright: ignore[reportUnknownVariableType]
            yield from _leaves(item)  # pyright: ignore[reportUnknownArgumentType]
    elif isinstance(value, list):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            yield from _leaves(item)  # pyright: ignore[reportUnknownArgumentType]
    else:
        yield value


def _exposure_factors() -> list[float | str]:
    """The resident-air factors and age-band rates the report prints from the settings."""
    settings = get_exposure_settings()
    f = settings.factors
    return [
        *settings.age_bands,
        f.exposure_time_hours_per_day,
        f.exposure_frequency_days_per_year,
        f.exposure_duration_years,
        f.lifetime_years,
        *(
            x
            for v in settings.age_bands.values()
            for x in (v.inhalation_rate_m3_per_day, v.body_weight_kg)
        ),
    ]


def _allowed(state: WorkspaceState) -> set[str]:
    """Every way the report may print a number of ``state`` or of the settings."""
    ctx = context()
    fmt, t = ctx.fmt, ctx.thresholds
    printed: list[str] = [str(n) for n in range(1, 9)]
    for leaf in [
        *_leaves(state.model_dump()),
        *vars(t).values(),
        *_exposure_factors(),
    ]:
        if isinstance(leaf, bool) or leaf is None:
            continue
        if isinstance(leaf, int | float):
            printed += [fmt.number(leaf), fmt.reported(leaf), str(leaf)]
            printed += [fmt.count(leaf)] if isinstance(leaf, int) else []
        else:
            printed.append(str(leaf))
    return {token for text in printed for token in _NUMBER.findall(text)}


def test_every_number_comes_from_the_workspace() -> None:
    state = assessed()
    text = lines(load(build_report(state, None, context(), WHEN)))
    body = text[text.index("1. Summary of findings") : text.index("8. Assessor summary")]
    allowed = _allowed(state)
    printed = {token for line in body for token in _NUMBER.findall(line)}
    assert printed - allowed == set()


def test_file_name_uses_cas_and_date() -> None:
    ctx = context()
    assert file_name(assessed(), ctx, WHEN) == "exposure-screening-11-11-1-2026-01-02.docx"


def test_file_name_never_carries_an_unexpected_cas() -> None:
    ctx = context()
    odd = WorkspaceState(chemical=Chemical(cas_number='1-11-1"; x=y'))
    assert file_name(odd, ctx, WHEN) == "exposure-screening-chemical-2026-01-02.docx"
    assert file_name(WorkspaceState(), ctx, WHEN) == "exposure-screening-chemical-2026-01-02.docx"


def test_has_findings() -> None:
    assert has_findings(assessed())
    assert has_findings(chemical_only())
    assert not has_findings(WorkspaceState())
