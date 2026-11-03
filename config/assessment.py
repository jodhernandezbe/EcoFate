"""Settings of the batch facility assessment (``[assessment]`` and ``[assessment.screening]``)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

from config.parsing import read_toml, require_int, require_number, section, subtable

_NAME = "assessment"
_SCREENING = "assessment.screening"


@dataclass(frozen=True)
class ScreeningSettings:
    """When a facility can be left out: its conservative bound is below both thresholds.

    Attributes:
        hq: Hazard quotient (unitless) at or above which a facility is assessed further.
        cancer_risk: Lifetime excess cancer risk (unitless) at or above which likewise.
        ambient_temperatures_k: Ambient temperatures (K) the worst case is taken over; the
            highest concentration counts (a hot day removes the buoyant rise of a cold stack).
    """

    hq: float
    cancer_risk: float
    ambient_temperatures_k: tuple[float, ...]


@dataclass(frozen=True)
class AssessmentSettings:
    """How the batch assessment screens, refines and assesses many facilities.

    Attributes:
        max_facilities: Most facilities fully assessed (site weather, residents) in one call.
        max_refined: Safety bound on the facilities given their own stacks and worst case in one
            call. Every facility reaching a threshold is refined; only the excess over this bound
            is left unassessed, and that is reported.
        max_workers: Facilities processed at the same time (each makes its own requests).
        scc_min_score: Lowest similarity (0-1) of an SCC match to the facility's industry for
            its PSTK stack to be used; below it the EPA global default stack is used.
        max_scc_stacks: Most distinct PSTK stacks used for one facility (evaluated as a range).
        inventory_cache_seconds: How long the inventory of a chemical (and place) is reused, so
            listing the facilities and then assessing them reads TRI once.
        max_worst_case_listed: Most worst-case-only facilities listed to the model (the rest
            are counted).
        max_screened_out_listed: Most screened-out facilities listed to the model, the closest
            to a threshold first (so a report has a table even when all were screened out).
        weather_cell_deg: Grid cell of the weather reanalysis (degrees); facilities in one
            cell share one weather request.
        screening: The thresholds and temperatures of the screen.
    """

    max_facilities: int
    max_refined: int
    max_workers: int
    scc_min_score: float
    max_scc_stacks: int
    inventory_cache_seconds: float
    max_worst_case_listed: int
    max_screened_out_listed: int
    weather_cell_deg: float
    screening: ScreeningSettings


def _temperatures(table: dict[str, object]) -> tuple[float, ...]:
    raw = table.get("ambient_temperatures_k")
    items = cast(list[object], raw) if isinstance(raw, list) else None
    if not items:
        raise ValueError(f"{_SCREENING}.ambient_temperatures_k must be a non-empty list")
    return tuple(
        require_number({"t": item}, "t", minimum=1e-9, name=f"{_SCREENING}.ambient_temperatures_k")
        for item in items
    )


def _screening(table: dict[str, object]) -> ScreeningSettings:
    screen = subtable(table, "screening", _NAME)
    return ScreeningSettings(
        hq=require_number(screen, "hq", minimum=1e-12, name=_SCREENING),
        cancer_risk=require_number(screen, "cancer_risk", minimum=1e-15, name=_SCREENING),
        ambient_temperatures_k=_temperatures(screen),
    )


def _score(table: dict[str, object]) -> float:
    score = require_number(table, "scc_min_score", minimum=1e-9, name=_NAME)
    if score > 1:
        raise ValueError(f"{_NAME}.scc_min_score must be at most 1")
    return score


def load_assessment_settings(path: Path | None = None) -> AssessmentSettings:
    """Load and validate the ``[assessment]`` table.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    return AssessmentSettings(
        max_facilities=_count(table, "max_facilities"),
        max_refined=_count(table, "max_refined"),
        max_workers=_count(table, "max_workers"),
        scc_min_score=_score(table),
        max_scc_stacks=_count(table, "max_scc_stacks"),
        inventory_cache_seconds=require_number(
            table,
            "inventory_cache_seconds",
            minimum=0,
            name=_NAME,
        ),
        max_worst_case_listed=_count(table, "max_worst_case_listed"),
        max_screened_out_listed=_count(table, "max_screened_out_listed"),
        weather_cell_deg=require_number(table, "weather_cell_deg", minimum=1e-9, name=_NAME),
        screening=_screening(table),
    )


def _count(table: dict[str, object], key: str) -> int:
    """A positive integer cap from the ``[assessment]`` table."""
    return require_int(table, key, minimum=1, name=_NAME)


@lru_cache(maxsize=1)
def get_assessment_settings() -> AssessmentSettings:
    """Return the cached assessment settings from the default file."""
    return load_assessment_settings()
