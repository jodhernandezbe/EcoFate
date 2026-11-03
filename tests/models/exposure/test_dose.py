"""Tests for models.exposure.dose."""

from __future__ import annotations

import numpy as np
import pytest

from models.exposure.dose import average_daily_dose, lifetime_average_daily_dose


def test_add() -> None:
    assert average_daily_dose(2.0, 20.0, 350.0, 30.0, 70.0, 10950.0) == pytest.approx(
        2.0 * 20.0 * 350.0 * 30.0 / (70.0 * 10950.0),
    )


def test_ladd_uses_lifetime() -> None:
    assert lifetime_average_daily_dose(1.0, 20.0, 350.0, 30.0, 70.0) == pytest.approx(
        average_daily_dose(1.0, 20.0, 350.0, 30.0, 70.0, 70 * 365),
    )


def test_array_concentration() -> None:
    out = average_daily_dose(np.array([1.0, 2.0]), 20.0, 350.0, 30.0, 70.0, 10950.0)
    assert isinstance(out, np.ndarray)
    assert out[1] == pytest.approx(2 * out[0])


def test_invalid() -> None:
    with pytest.raises(ValueError):
        average_daily_dose(1.0, 20.0, 350.0, 30.0, 0.0, 10950.0)
