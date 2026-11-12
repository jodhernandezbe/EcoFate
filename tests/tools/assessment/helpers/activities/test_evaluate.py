"""Tests for one worker activity (bundled ChemSTEER settings, a synthetic chemical)."""

from __future__ import annotations

import dataclasses

import pytest

from commons.units import convert
from config.ecetoc_tra import get_ecetoc_tra_settings
from config.occupational import OccupationalSettings, get_occupational_settings
from models.exposure import vapor_generation as vg
from tools.assessment.helpers.activities.evaluate import (
    OUT_OF_RANGE,
    ActivityResult,
    Chemical,
    Context,
    evaluate,
    saturation_mg_m3,
    volatility,
)
from tools.assessment.helpers.occupational_bands.ecetoc import load_table

SETTINGS = get_occupational_settings()
TRA = get_ecetoc_tra_settings()
WITHIN = Chemical(molecular_weight=100.0, vapor_pressure_torr=10.0)
ABOVE = Chemical(molecular_weight=100.0, vapor_pressure_torr=95.0)
BELOW = Chemical(molecular_weight=100.0, vapor_pressure_torr=0.0001)


def _ctx(chemical: Chemical, settings: OccupationalSettings = SETTINGS) -> Context:
    return Context(chemical, settings, load_table(TRA.table_path), TRA)


def _run(key: str, chemical: Chemical = WITHIN) -> ActivityResult:
    result = evaluate(SETTINGS.activities[key], _ctx(chemical))
    assert result is not None
    return result


def test_volatility_against_the_range() -> None:
    assert volatility(0.0001, SETTINGS) == "below"
    assert volatility(10.0, SETTINGS) == "within"
    assert volatility(95.0, SETTINGS) == "above"


def test_drum_loading_is_a_mass_balance_over_the_full_shift() -> None:
    result = _run("drum_loading")
    case = result.typical
    expected_g = vg.loading_rate(0.5, 100.0, 55.0, 20.0, 10.0, 298.0)
    q = convert(3000.0, "ft^3/min", "m^3/s")
    assert case.estimator == "mass_balance"
    assert case.generation_g_per_s == pytest.approx(expected_g)
    assert case.concentration_mg_m3 == pytest.approx(expected_g * 1000.0 / (q * 0.5))
    assert case.twa_mg_m3 == pytest.approx(case.concentration_mg_m3)


def test_indoor_sampling_is_the_near_field_over_one_hour() -> None:
    case = _run("liquid_sampling").typical
    assert case.estimator == "two_zone"
    assert (case.room_m3, case.air_exchange_per_h) == (2000.0, 15.0)
    assert case.concentration_mg_m3 is not None
    assert case.twa_mg_m3 == pytest.approx(case.concentration_mg_m3 / 8.0)


def test_equipment_cleaning_uses_outdoor_ventilation() -> None:
    result = _run("equipment_cleaning")
    assert result.typical.airflow_m3_per_s == pytest.approx(convert(237_600.0, "ft^3/min", "m^3/s"))
    assert result.worst_case.airflow_m3_per_s == pytest.approx(
        convert(132_000.0, "ft^3/min", "m^3/s"),
    )


@pytest.mark.parametrize("key", sorted(SETTINGS.activities))
def test_worst_case_is_at_least_typical(key: str) -> None:
    result = _run(key)
    assert result.worst_case.twa_mg_m3 >= result.typical.twa_mg_m3


def test_below_the_range_nothing_is_computed() -> None:
    assert evaluate(SETTINGS.activities["drum_loading"], _ctx(BELOW)) is None


def test_loading_above_the_range_is_computed_as_usual() -> None:
    result = _run("drum_loading", ABOVE)
    assert result.typical.estimator == "mass_balance"
    assert result.warnings == ()


def test_sampling_above_the_range_takes_the_ecetoc_estimate() -> None:
    result = _run("liquid_sampling", ABOVE)  # 95 torr is about 12.7 kPa: the high band
    worst = 250.0 * 100.0 / 24.45  # PROC 8a, high volatility, industrial, no LEV (TR 114)
    assert result.worst_case.estimator == "ecetoc_tra"
    assert result.worst_case.twa_mg_m3 == pytest.approx(worst)
    assert result.typical.twa_mg_m3 == pytest.approx(worst * 0.6)  # 1 h: the 1-4 h modifier
    assert result.statement is not None


def test_evaporation_above_the_range_without_a_band_value_warns() -> None:
    result = _run("container_cleaning", ABOVE)  # no ECETOC process category
    assert result.typical.estimator == "two_zone"
    assert result.warnings == (OUT_OF_RANGE,)


def test_the_saturation_concentration_caps_the_air() -> None:
    choked = dataclasses.replace(
        SETTINGS,
        indoor=dataclasses.replace(
            SETTINGS.indoor,
            worst_case=dataclasses.replace(SETTINGS.indoor.worst_case, rate_ft3_per_min=1e-9),
        ),
    )
    result = evaluate(choked.activities["drum_loading"], _ctx(WITHIN, choked))
    assert result is not None
    assert result.worst_case.capped
    assert result.worst_case.concentration_mg_m3 == pytest.approx(
        saturation_mg_m3(WITHIN, SETTINGS),
    )
    assert not result.typical.capped
