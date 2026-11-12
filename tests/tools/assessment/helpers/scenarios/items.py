"""Assessed facilities for the scenario tests, with the real screening equations.

The numbers are placeholders (round values), not data about any facility.
"""

from __future__ import annotations

from config.exposure import get_exposure_settings
from config.occupational import get_occupational_settings
from tests.tools.assessment.factories import PEOPLE, WEATHER, record, stack
from tools.assessment.helpers.occupational import Workplace, occupational_exposure
from tools.exposure.helpers.facility import assess_facility
from tools.schemas import (
    FacilityAssessment,
    OccupationalLimits,
    OperationalProfile,
    Population,
    StackParameters,
    Toxicity,
    TractReceptor,
)

RATE = 0.5  # g/s, a placeholder
LOW, HIGH = stack(5.0), stack(60.0)
BOTH = Toxicity(rfc=1e-3, iur=1e-6)  # RfC mg/m^3 and IUR (ug/m^3)^-1, placeholders


def tract(geoid: str, distance_m: float, residents: int = 100) -> TractReceptor:
    """A census tract at a distance, with a generic age mix."""
    return TractReceptor(
        geoid=geoid,
        residents=residents,
        age_distribution={"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0},
        distance_m=distance_m,
        bearing_deg=90.0,
        latitude=41.5,
        longitude=-71.19,
        land_area_km2=1.0,
    )


def population(tracts: list[TractReceptor]) -> Population:
    """The placeholder population with the given tracts."""
    return {**PEOPLE, "tracts": tracts, "tracts_not_listed": 0}


def profile() -> OperationalProfile:
    """A worker schedule of 250 days at 16 hours."""
    return OperationalProfile(
        naics_code="325199",
        life_cycle_stage=["Manufacturing"],
        cou_category=[],
        cdr_sector=None,
        days_per_week=5,
        operating_days_per_year=250.0,
        hours_per_day=16.0,
        annual_operating_hours=4000.0,
        schedule_source="test schedule",
        warnings=[],
    )


def worker(oel: float | None = 5.0, toxicity: Toxicity = BOTH, vapor_pressure: float = 10.0):  # noqa: ANN201
    """The real worker screening of a manufacturing facility, for a chemical of 100 g/mol."""
    limits = OccupationalLimits(
        oel_twa_mg_m3=oel,
        oel_source=None if oel is None else "OSHA PEL-TWA (PubChem)",
        limits={},
        reasons={},
        warnings=[],
    )
    place = Workplace(
        get_occupational_settings(),
        limits,
        None,
        100.0,
        "test",
        vapor_pressure,
        "test",
    )
    row = record(fugitive_release_kg_per_year=1000.0, fugitive_reporting_year=2020)
    return occupational_exposure(row, profile(), toxicity, place)


def assessed(
    frs_id: str = "F1",
    *,
    stacks: list[StackParameters] | None = None,
    toxicity: Toxicity = BOTH,
    tracts: list[TractReceptor] | None = None,
    level: str = "full",
    oel: float | None = 5.0,
    vapor_pressure: float = 10.0,
) -> FacilityAssessment:
    """A facility assessed with the real equations (no scenarios attached yet)."""
    chosen = stacks if stacks is not None else [LOW, HIGH]
    row = record(frs_id, emission_rate=RATE)
    full = level == "full"
    exposure = assess_facility(RATE, chosen, WEATHER, PEOPLE, toxicity, get_exposure_settings())
    return FacilityAssessment(
        record=row,
        level="full" if full else "worst case only",
        bound=None,
        stacks=chosen,
        stack_tier="NEI",
        scc_matches=[],
        industry=None,
        meteorology=WEATHER if full else None,
        population=population(tracts or []) if full else None,
        radius_km=None,
        exposure=exposure,
        occupational_exposure=worker(oel, toxicity, vapor_pressure),
        operational_profile=profile(),
        notes=[],
    )
