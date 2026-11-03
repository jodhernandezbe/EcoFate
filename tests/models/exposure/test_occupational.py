"""Tests for the worker screening arithmetic."""

from __future__ import annotations

import math

import pytest

from models.exposure import occupational as occ

EXCEED = (1.0, 1.0, 1e-4)
ELEVATED = (0.1, 0.1, 1e-6)


def _tier(
    ratio: float | None = None,
    hq: float | None = None,
    risk: float | None = None,
) -> str | None:
    return occ.risk_tier(ratio, hq, risk, exceedance=EXCEED, elevated=ELEVATED)


def test_generation_rate_worked_example() -> None:
    assert occ.generation_rate(1000.0, 250.0, 16.0) == pytest.approx(1000e6 / (250 * 16 * 3600))


def test_concentration_worked_example() -> None:
    g = occ.generation_rate(1000.0, 250.0, 16.0)
    assert occ.workplace_concentration(g, 1.416, 0.5) == pytest.approx(g / 0.708)


def test_doubled_release_doubles_concentration() -> None:
    one = occ.workplace_concentration(occ.generation_rate(10.0, 250, 8), 1.0, 0.5)
    two = occ.workplace_concentration(occ.generation_rate(20.0, 250, 8), 1.0, 0.5)
    assert two == pytest.approx(2 * one)


def test_less_ventilation_or_mixing_raises_concentration() -> None:
    base = occ.workplace_concentration(5.0, 1.0, 0.5)
    assert occ.workplace_concentration(5.0, 0.5, 0.5) > base
    assert occ.workplace_concentration(5.0, 1.0, 0.1) > base


@pytest.mark.parametrize(
    "call",
    [
        lambda: occ.generation_rate(1.0, 250.0, 0.0),
        lambda: occ.generation_rate(math.nan, 250.0, 8.0),
        lambda: occ.generation_rate(-1.0, 250.0, 8.0),
        lambda: occ.generation_rate(True, 250.0, 8.0),
        lambda: occ.workplace_concentration(1.0, 1.0, 1.5),
        lambda: occ.workplace_concentration(1.0, 0.0, 0.5),
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


def test_tier_exceedance_elevated_acceptable() -> None:
    assert _tier(ratio=1.2, hq=0.0, risk=0.0) == "exceedance"
    assert _tier(ratio=0.0, hq=1.5) == "exceedance"
    assert _tier(risk=2e-4) == "exceedance"
    assert _tier(ratio=0.01, hq=0.01, risk=5e-6) == "elevated"
    assert _tier(ratio=0.5) == "elevated"
    assert _tier(ratio=0.01, hq=0.01, risk=1e-8) == "acceptable"


def test_tier_boundaries_are_strict() -> None:
    assert _tier(ratio=1.0) == "elevated"
    assert _tier(ratio=0.1) == "acceptable"


def test_tier_ignores_null_and_is_null_when_nothing_to_compare() -> None:
    assert _tier(ratio=None, hq=2.0, risk=None) == "exceedance"
    assert _tier() is None
