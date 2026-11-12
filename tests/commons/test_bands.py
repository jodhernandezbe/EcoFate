"""Tests for the three screening bands."""

from __future__ import annotations

import math

import pytest

from commons.bands import band_of, highest_band

HQ = (0.1, 1.0)
RISK = (1e-6, 1e-4)


def test_high_by_one_quantity() -> None:
    assert highest_band([(1.2, *HQ), (1e-7, *RISK)]) == "high"


def test_moderate_by_cancer_risk() -> None:
    assert highest_band([(0.05, *HQ), (5e-6, *RISK)]) == "moderate"


def test_on_the_upper_boundary_is_high() -> None:
    assert band_of(1.0, *HQ) == "high"


def test_on_the_lower_boundary_is_moderate() -> None:
    assert band_of(0.1, *HQ) == "moderate"


def test_low() -> None:
    assert highest_band([(0.01, *HQ), (1e-8, *RISK)]) == "low"


def test_zero_is_low() -> None:
    assert band_of(0.0, *HQ) == "low"


def test_nothing_to_compare_is_none_not_low() -> None:
    assert highest_band([(None, *HQ), (None, *RISK)]) is None
    assert highest_band([]) is None


def test_missing_value_does_not_count() -> None:
    assert highest_band([(None, *HQ), (2e-6, *RISK)]) == "moderate"


@pytest.mark.parametrize("value", [math.nan, math.inf, -1.0, True])
def test_invalid_value(value: float) -> None:
    with pytest.raises(ValueError, match="value"):
        band_of(value, *HQ)


@pytest.mark.parametrize(("lower", "upper"), [(1.0, 1.0), (2.0, 1.0), (0.0, 1.0), (0.1, math.nan)])
def test_invalid_boundaries(lower: float, upper: float) -> None:
    with pytest.raises(ValueError, match="boundary"):
        band_of(0.5, lower, upper)
