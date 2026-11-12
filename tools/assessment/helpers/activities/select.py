"""Which worker activities a facility is evaluated for (design D3).

For each TSCA life cycle stage the facility's Form R flags give, the facility gets every activity
of ChemSTEER's generic operation of that stage, plus the activities of each crosswalk row of its
CDR industrial sector and that stage. The union is taken over stages and rows, each activity once.
A scenario document adds activities and never removes one; no sector is ever inferred.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from config.occupational import OccupationalSettings
from tools.assessment.helpers.activities.crosswalk import Crosswalk, ScenarioRow

NO_ACTIVITY = "the facility reported no activity"
NO_SECTOR = "the facility's NAICS code maps to no CDR industrial sector"


@dataclass(frozen=True)
class StageRoute:
    """How the activities of one life cycle stage were chosen.

    Attributes:
        stage: TSCA life cycle stage.
        generic_activities: Activity keys of ChemSTEER's generic operation of the stage.
        scenarios: The crosswalk rows (generic scenario or ESD) that also applied.
        note: Why no scenario document applied, or None.
    """

    stage: str
    generic_activities: tuple[str, ...]
    scenarios: tuple[ScenarioRow, ...]
    note: str | None


@dataclass(frozen=True)
class Selection:
    """The activities chosen for a facility and the routes that chose them.

    Attributes:
        activities: Activity keys, each once, in the order first met.
        routes: One route per stage that has a generic operation.
        reason: Why there is no activity, or None.
        notes: Stages skipped and other facts about the walk.
    """

    activities: tuple[str, ...]
    routes: tuple[StageRoute, ...]
    reason: str | None
    notes: tuple[str, ...]


def _route(
    stage: str,
    sector: str | None,
    generic: tuple[str, ...],
    crosswalk: Crosswalk,
) -> StageRoute:
    rows = crosswalk.rows_for(sector, stage) if sector else ()
    note = None
    if sector and not rows:
        note = f"no generic scenario document of sector {sector} applies at {stage}"
    return StageRoute(stage, generic, rows, note)


def _keys(route: StageRoute) -> list[str]:
    return [*route.generic_activities, *(a for row in route.scenarios for a in row.activities)]


def _skipped(stages: Sequence[str], settings: OccupationalSettings) -> list[str]:
    return [
        f"{stage} has no ChemSTEER generic operation, so it is not modelled"
        for stage in stages
        if stage not in settings.stage_activities
    ]


def select_activities(
    stages: Sequence[str],
    sector: str | None,
    settings: OccupationalSettings,
    crosswalk: Crosswalk,
) -> Selection:
    """The activities of a facility from its life cycle stages and CDR sector code.

    Args:
        stages: The TSCA stages the facility's Form R flags give.
        sector: The facility's CDR industrial sector code (e.g. "IS13"), or None.
        settings: The occupational settings (the generic operation of each stage).
        crosswalk: The validated crosswalk of sector and stage to generic scenarios.

    Returns:
        The activity keys (each once), the route of each stage, and the reason there is none.
    """
    if not stages:
        return Selection((), (), NO_ACTIVITY, ())
    known = [s for s in dict.fromkeys(stages) if s in settings.stage_activities]
    routes = tuple(_route(s, sector, settings.stage_activities[s], crosswalk) for s in known)
    keys = tuple(dict.fromkeys(k for route in routes for k in _keys(route)))
    notes = [*_skipped(list(dict.fromkeys(stages)), settings), *([] if sector else [NO_SECTOR])]
    reason = None if keys else "none of the facility's life cycle stages has a generic operation"
    return Selection(keys, routes, reason, tuple(notes))
