"""Tests for the ChemSTEER vapor generation models and the saturation concentration."""

from __future__ import annotations

import math

import pytest

from models.exposure import vapor_generation as vg

T = 298.0


def test_loading_formula() -> None:
    expected = 0.5 * 100 * (3785.4 * 55) * 20 * (10 / 760) / (3600 * T * 82.05)
    assert vg.loading_rate(0.5, 100.0, 55.0, 20.0, 10.0, T) == pytest.approx(expected)


def test_loading_proportional_to_vapor_pressure() -> None:
    one = vg.loading_rate(1.0, 100.0, 55.0, 20.0, 10.0, T)
    assert vg.loading_rate(1.0, 100.0, 55.0, 20.0, 20.0, T) == pytest.approx(2 * one)


def test_penetration_formula() -> None:
    mw, vp, vz, d = 100.0, 10.0, 100.0, 2.53
    area = math.pi * d**2 / 4
    expected = (8.24e-8 * mw**0.835 * vp * (1 / 29 + 1 / mw) ** 0.25 * vz**0.5 * area) / (
        T**0.05 * d**0.5 * 1.0**0.5
    )
    assert vg.penetration_rate(mw, vp, vz, d, T) == pytest.approx(expected)


def test_mass_transfer_formula() -> None:
    mw, vp, vz, d = 100.0, 10.0, 440.0, 92.0
    area = math.pi * d**2 / 4
    expected = (1.93e-7 * mw**0.78 * vp * (1 / 29 + 1 / mw) ** 0.33 * vz**0.78 * area) / (
        T**0.4 * d**0.11 * (T**0.5 - 5.87) ** (2 / 3)
    )
    assert vg.mass_transfer_rate(mw, vp, vz, d, T) == pytest.approx(expected)


def test_larger_opening_evaporates_more() -> None:
    small = vg.penetration_rate(100.0, 10.0, 100.0, 2.53, T)
    assert vg.penetration_rate(100.0, 10.0, 100.0, 10.0, T) > small
    small = vg.mass_transfer_rate(100.0, 10.0, 440.0, 10.0, T)
    assert vg.mass_transfer_rate(100.0, 10.0, 440.0, 92.0, T) > small


def test_correction_factor_scales_rate() -> None:
    full = vg.penetration_rate(100.0, 10.0, 100.0, 2.53, T)
    assert vg.penetration_rate(100.0, 10.0, 100.0, 2.53, T, correction=0.5) == pytest.approx(
        full / 2,
    )


def test_wrong_model_for_air_speed() -> None:
    with pytest.raises(ValueError, match="at or below 100"):
        vg.penetration_rate(100.0, 10.0, 440.0, 2.53, T)
    with pytest.raises(ValueError, match="above 100"):
        vg.mass_transfer_rate(100.0, 10.0, 100.0, 92.0, T)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"saturation_factor": 1.5}, "saturation_factor"),
        ({"molecular_weight": 0.0}, "molecular_weight"),
        ({"vapor_pressure_torr": math.nan}, "vapor_pressure_torr"),
        ({"vapor_pressure_torr": -1.0}, "vapor_pressure_torr"),
        ({"container_gallons": 0.0}, "container_gallons"),
        ({"correction": 0.0}, "correction"),
        ({"temperature_k": True}, "temperature_k"),
    ],
)
def test_loading_invalid_input(kwargs: dict[str, float], match: str) -> None:
    args: dict[str, float] = {
        "saturation_factor": 0.5,
        "molecular_weight": 100.0,
        "container_gallons": 55.0,
        "fill_rate_per_hour": 20.0,
        "vapor_pressure_torr": 10.0,
        "temperature_k": T,
    }
    args.update(kwargs)
    with pytest.raises(ValueError, match=match):
        vg.loading_rate(**args)


@pytest.mark.parametrize(
    ("diameter", "pressure"),
    [(0.0, 1.0), (math.inf, 1.0), (2.53, 0.0)],
)
def test_penetration_invalid_input(diameter: float, pressure: float) -> None:
    with pytest.raises(ValueError):
        vg.penetration_rate(100.0, 10.0, 100.0, diameter, T, pressure_atm=pressure)


def test_mass_transfer_rejects_temperature_outside_correlation() -> None:
    with pytest.raises(ValueError, match="temperature"):
        vg.mass_transfer_rate(100.0, 10.0, 440.0, 92.0, 30.0)


def test_zero_vapor_pressure_generates_nothing() -> None:
    assert vg.penetration_rate(100.0, 0.0, 100.0, 2.53, T) == 0.0
    assert vg.loading_rate(1.0, 100.0, 55.0, 20.0, 0.0, T) == 0.0


def test_saturation_formula() -> None:
    assert vg.saturation_concentration(100.0, 76.0, 24.45) == pytest.approx(1e5 * 100 / 24.45)


def test_saturation_of_zero_vapor_pressure_is_zero() -> None:
    assert vg.saturation_concentration(100.0, 0.0, 24.45) == 0.0


def test_saturation_invalid_input() -> None:
    with pytest.raises(ValueError, match="molar_volume"):
        vg.saturation_concentration(100.0, 76.0, 0.0)
