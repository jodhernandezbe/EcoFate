"""Tests for the worker screening arithmetic."""

from __future__ import annotations

import math

import pytest

from models.exposure import occupational as occ

INF = math.inf


def test_concentration_worked_example() -> None:
    result = occ.workplace_concentration(10.0, 1.416, 0.5, INF)
    assert result.concentration_mg_per_m3 == pytest.approx(10.0 / 0.708) and not result.capped


def test_concentration_is_capped_at_saturation() -> None:
    result = occ.workplace_concentration(5.0, 1.0, 0.5, 4.0)
    assert result.concentration_mg_per_m3 == 4.0 and result.capped


def test_a_mass_balance_equal_to_saturation_is_not_capped() -> None:
    result = occ.workplace_concentration(5.0, 1.0, 0.5, 10.0)
    assert result.concentration_mg_per_m3 == 10.0 and not result.capped


def test_doubled_generation_doubles_concentration() -> None:
    one = occ.workplace_concentration(10.0, 1.0, 0.5, INF)
    two = occ.workplace_concentration(20.0, 1.0, 0.5, INF)
    assert two.concentration_mg_per_m3 == pytest.approx(2 * one.concentration_mg_per_m3)


def test_less_ventilation_or_mixing_raises_concentration() -> None:
    base = occ.workplace_concentration(5.0, 1.0, 0.5, INF).concentration_mg_per_m3
    assert occ.workplace_concentration(5.0, 0.5, 0.5, INF).concentration_mg_per_m3 > base
    assert occ.workplace_concentration(5.0, 1.0, 0.1, INF).concentration_mg_per_m3 > base


@pytest.mark.parametrize(
    "call",
    [
        lambda: occ.workplace_concentration(math.nan, 1.0, 0.5, INF),
        lambda: occ.workplace_concentration(-1.0, 1.0, 0.5, INF),
        lambda: occ.workplace_concentration(1.0, 1.0, 1.5, INF),
        lambda: occ.workplace_concentration(1.0, 0.0, 0.5, INF),
        lambda: occ.workplace_concentration(1.0, 1.0, 0.5, -1.0),
        lambda: occ.workplace_concentration(1.0, 1.0, 0.5, math.nan),
    ],
)
def test_invalid_box_inputs_raise(call: object) -> None:
    with pytest.raises(ValueError):
        call()  # type: ignore[operator]


def test_twa_caps_long_shift_and_dilutes_short_one() -> None:
    assert occ.twa_concentration(2.0, 16.0) == pytest.approx(2.0)
    assert occ.twa_concentration(2.0, 4.0) == pytest.approx(1.0)


def test_oel_ratio() -> None:
    assert occ.oel_ratio(0.5, 5.0) == pytest.approx(0.1)
    with pytest.raises(ValueError):
        occ.oel_ratio(0.5, 0.0)


def test_adc_tenure_cancels() -> None:
    adc = occ.worker_average_concentration(1.0, 10.0, 20.0, 250.0, 40.0, 40.0)
    assert adc == pytest.approx(0.5 * 250 / 365)


def test_ladc_scales_with_tenure_over_lifetime() -> None:
    adc = occ.worker_average_concentration(1.0, 10.0, 20.0, 250.0, 40.0, 40.0)
    ladc = occ.worker_average_concentration(1.0, 10.0, 20.0, 250.0, 40.0, 78.0)
    assert ladc == pytest.approx(adc * 40 / 78)


def test_worker_average_rejects_impossible_schedule() -> None:
    with pytest.raises(ValueError):
        occ.worker_average_concentration(1.0, 10.0, 20.0, 366.0, 40.0, 78.0)
    with pytest.raises(ValueError):
        occ.worker_average_concentration(1.0, 30.0, 20.0, 250.0, 40.0, 78.0)
    with pytest.raises(ValueError):
        occ.worker_average_concentration(1.0, 10.0, 20.0, 250.0, 80.0, 78.0)


def test_cancer_risk_units() -> None:
    assert occ.worker_cancer_risk(0.001, 1e-6) == pytest.approx(1e-6)


def test_hazard_quotient_and_rejections() -> None:
    assert occ.worker_hazard_quotient(0.5, 1.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        occ.worker_hazard_quotient(0.5, 0.0)
    with pytest.raises(ValueError):
        occ.worker_cancer_risk(0.5, -1.0)


@pytest.mark.parametrize(("speed", "expected"), [(440.0, 132_000.0), (792.0, 237_600.0)])
def test_outdoor_ventilation_table_b2a(speed: float, expected: float) -> None:
    assert occ.outdoor_ventilation_ft3_per_min(26_400.0, speed) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("coefficient", "speed"),
    [(0.0, 440.0), (26_400.0, 0.0), (-1.0, 440.0), (26_400.0, math.nan), (True, 440.0)],
)
def test_outdoor_ventilation_rejects_invalid_inputs(coefficient: float, speed: float) -> None:
    with pytest.raises(ValueError):
        occ.outdoor_ventilation_ft3_per_min(coefficient, speed)
