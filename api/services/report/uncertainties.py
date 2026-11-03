"""Section 7: every warning, screening default and unattributed result in the workspace."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from docx.document import Document

from api.schemas.workspace import Facility, Meteorology, Receptors, WorkspaceState
from api.services.report.document import (
    ReportContext,
    bullets,
    empty,
    facility_label,
    subheading,
)

Group = tuple[str, list[str]]


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def _defaults(receptors: Receptors | None, met: Meteorology | None) -> list[str]:
    found: list[str] = []
    if receptors and receptors.screening_default:
        found.append(f"Receptor population is a screening default ({receptors.source}).")
    if met and met.screening_default:
        found.append(f"Meteorology is a screening default ({met.source}).")
    return found


def _facility(facility: Facility) -> list[str]:
    exposure, receptors, met = facility.exposure, facility.receptors, facility.meteorology
    return _unique(
        [
            *(w for stack in facility.stacks for w in stack.warnings),
            *(exposure.warnings if exposure else []),
            *(receptors.warnings if receptors else []),
            *(met.warnings if met else []),
            *_defaults(receptors, met),
        ],
    )


def _unattached(state: WorkspaceState) -> list[str]:
    """The thread's latest weather when it belongs to no facility of the workspace."""
    met, held = state.meteorology, {f.frs_id for f in state.facilities}
    if met is None or met.frs_id in held:
        return []
    return _unique([*met.warnings, *_defaults(None, met)])


def warning_groups(state: WorkspaceState) -> list[Group]:
    """Non-empty groups of findings, in report order."""
    chemical = state.chemical
    groups: Iterator[Group] = iter(
        [
            ("Workspace", _unique(state.warnings)),
            ("Chemical", _unique([*chemical.warnings, *chemical.read_across.warnings])),
            *((facility_label(f), _facility(f)) for f in state.facilities),
            ("Meteorology not attached to a facility", _unattached(state)),
            ("Unattributed results", _unique(f"{u.tool}: {u.reason}" for u in state.unattributed)),
        ],
    )
    return [(title, items) for title, items in groups if items]


def write_uncertainties(doc: Document, state: WorkspaceState, ctx: ReportContext) -> None:
    """One bulleted group per place a finding arose, or the empty-section sentence."""
    groups = warning_groups(state)
    if not groups:
        empty(doc, ctx)
        return
    for title, items in groups:
        subheading(doc, title)
        bullets(doc, items)
