"""Tests for the worker screening of one facility (synthetic round numbers)."""

from __future__ import annotations

import pytest

from config.occupational import get_occupational_settings
from tests.tools.assessment.factories import record
from tools.assessment.helpers.occupational import Workplace, no_limits, occupational_exposure
from tools.schemas import OccupationalLimits, OperationalProfile, Toxicity

SETTINGS = get_occupational_settings()
BASELINE_Q = 3000 * 0.3048**3 / 60  # ft^3/min -> m^3/s
WORST_Q = 500 * 0.3048**3 / 60


def _limits(oel: float | None = 5.0) -> OccupationalLimits:
    return OccupationalLimits(
        oel_twa_mg_m3=oel,
        oel_source=None if oel is None else "OSHA PEL-TWA (PubChem)",
        limits={},
        reasons={},
        warnings=[],
    )


def _workplace(oel: float | None = 5.0, pressure: float | None = 10.0) -> Workplace:
    source = None if pressure is None else "CompTox (experimental)"
    return Workplace(SETTINGS, _limits(oel), pressure, source)


def _profile(days: float | None = 250.0, hours: float | None = 16.0) -> OperationalProfile:
    return OperationalProfile(
        naics_code="325199",
        life_cycle_stage=[],
        cou_category=[],
        cdr_sector=None,
        days_per_week=5,
        operating_days_per_year=days,
        hours_per_day=hours,
        annual_operating_hours=None if days is None or hours is None else days * hours,
        schedule_source="test",
        warnings=[],
    )


def _record(kg: float | None = 1000.0):  # noqa: ANN202
    return record(fugitive_release_kg_per_year=kg, fugitive_reporting_year=2020)


TOX = Toxicity(rfc=1.0, iur=1e-6)


def test_box_model_for_both_tiers() -> None:
    result = occupational_exposure(_record(), _profile(), TOX, _workplace())
    generation = 1000 * 1e6 / (250 * 16 * 3600)
    assert result["baseline"]["workplace_concentration_mg_m3"] == pytest.approx(
        generation / (BASELINE_Q * 0.5),
    )
    assert result["worst_case"]["workplace_concentration_mg_m3"] == pytest.approx(
        generation / (WORST_Q * 0.1),
    )
    base, worst = result["baseline"], result["worst_case"]
    assert base["workplace_concentration_mg_m3"] is not None
    assert worst["workplace_concentration_mg_m3"] is not None
    assert worst["workplace_concentration_mg_m3"] > base["workplace_concentration_mg_m3"]
    assert result["baseline"]["ventilation_m3_per_s"] == pytest.approx(1.416, abs=1e-3)


def test_twa_ratio_hq_and_cancer_risk_follow_the_equations() -> None:
    tier = occupational_exposure(_record(), _profile(), TOX, _workplace())["baseline"]
    twa = tier["workplace_concentration_mg_m3"]
    assert twa is not None and tier["twa_mg_m3"] == pytest.approx(twa)  # 16 h shift caps at 8
    assert tier["oel_ratio"] == pytest.approx(twa / 5.0)
    adc = twa * 0.5 * 250 / 365
    assert tier["hq"] == pytest.approx(adc / 1.0)
    assert tier["cancer_risk"] == pytest.approx(adc * 40 / 78 * 1000 * 1e-6)


def test_short_shift_dilutes_the_twa_and_fewer_days_cap_the_worker() -> None:
    tier = occupational_exposure(_record(), _profile(days=100.0, hours=4.0), TOX, _workplace())[
        "baseline"
    ]
    conc = tier["workplace_concentration_mg_m3"]
    assert conc is not None and tier["twa_mg_m3"] == pytest.approx(conc / 2)
    assert tier["hq"] == pytest.approx(tier["twa_mg_m3"] * 0.5 * 100 / 365)  # type: ignore[operator]


def test_no_fugitive_release_gives_nulls_not_zero() -> None:
    result = occupational_exposure(_record(None), _profile(), TOX, _workplace())
    assert result["baseline"]["workplace_concentration_mg_m3"] is None
    assert result["risk_tier"] is None and result["worst_case"]["risk_tier"] is None
    assert any("no fugitive air release" in w for w in result["warnings"])


def test_a_reported_zero_is_acceptable_when_there_is_a_benchmark() -> None:
    result = occupational_exposure(_record(0.0), _profile(), TOX, _workplace())
    assert result["baseline"]["workplace_concentration_mg_m3"] == 0.0
    assert result["risk_tier"] == "acceptable"


def test_no_benchmark_leaves_only_the_hq_and_risk_that_have_one() -> None:
    result = occupational_exposure(
        _record(),
        _profile(),
        Toxicity(rfc=1.0, iur=None),
        _workplace(oel=None),
    )
    tier = result["baseline"]
    assert tier["oel_ratio"] is None and tier["hq"] is not None and tier["cancer_risk"] is None
    joined = " ".join(result["warnings"])
    assert "no 8-hour occupational limit" in joined and "no IUR" in joined


def test_nothing_to_compare_gives_no_tier() -> None:
    result = occupational_exposure(
        _record(),
        _profile(),
        Toxicity(rfc=None, iur=None),
        _workplace(oel=None),
    )
    assert result["risk_tier"] is None and result["baseline"]["twa_mg_m3"] is not None


def test_exceedance_by_the_limit() -> None:
    result = occupational_exposure(_record(1.0e6), _profile(), TOX, _workplace(oel=0.001))
    assert result["risk_tier"] == "exceedance"
    assert result["baseline"]["oel_ratio"] is not None and result["baseline"]["oel_ratio"] > 1


def test_vapor_pressure_is_context_and_only_warns_when_non_volatile() -> None:
    volatile = occupational_exposure(_record(), _profile(), TOX, _workplace(pressure=10.0))
    low = occupational_exposure(_record(), _profile(), TOX, _workplace(pressure=1e-5))
    unknown = occupational_exposure(_record(), _profile(), TOX, _workplace(pressure=None))
    assert not any("vapor pressure" in w for w in volatile["warnings"] + unknown["warnings"])
    assert any("vapor pressure" in w for w in low["warnings"])
    assert volatile["baseline"] == low["baseline"] == unknown["baseline"]
    assert volatile["vapor_pressure_source"] == "CompTox (experimental)"
    assert unknown["vapor_pressure_mmhg"] is None


def test_no_schedule_gives_nulls() -> None:
    result = occupational_exposure(_record(), _profile(days=None, hours=None), TOX, _workplace())
    assert result["baseline"]["twa_mg_m3"] is None
    assert any("schedule" in w for w in result["warnings"])


def test_assumptions_are_stated() -> None:
    text = " ".join(occupational_exposure(_record(), _profile(), TOX, _workplace())["assumptions"])
    assert (
        "well-mixed" in text and "not an OSHA compliance" in text and "screening defaults" in text
    )


def test_no_limits_helper() -> None:
    assert no_limits("why")["warnings"] == ["why"] and no_limits("why")["oel_twa_mg_m3"] is None
