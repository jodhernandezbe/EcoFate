"""Tests for models.transport.plume_rise (EPA-454/R-92-019 equations 4.1, 4.2, 4.6, 4.7)."""

from __future__ import annotations

import math

import pytest

from models.transport.plume_rise import buoyancy_flux, final_plume_rise, stack_tip_downwash


def test_buoyancy_flux_hand_computed() -> None:
    # 9.806 * 10 * 2^2 * (400 - 300) / (4 * 400) = 24.515
    assert buoyancy_flux(10.0, 2.0, 400.0, 300.0) == pytest.approx(24.515)


def test_no_buoyancy_when_the_gas_is_not_warmer() -> None:
    assert buoyancy_flux(10.0, 2.0, 300.0, 300.0) == 0.0
    assert buoyancy_flux(10.0, 2.0, 280.0, 300.0) == 0.0


def test_hotter_gas_has_more_flux() -> None:
    assert buoyancy_flux(10.0, 2.0, 500.0, 300.0) > buoyancy_flux(10.0, 2.0, 400.0, 300.0)


@pytest.mark.parametrize(
    "args",
    [
        (0.0, 2.0, 400.0, 300.0),
        (10.0, -2.0, 400.0, 300.0),
        (10.0, 2.0, 0.0, 300.0),
        (10.0, 2.0, 400.0, math.nan),
        (True, 2.0, 400.0, 300.0),
    ],
)
def test_buoyancy_flux_rejects_impossible_input(args: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        buoyancy_flux(*args)


def test_low_flux_regime_unstable_and_neutral() -> None:
    expected = 21.4 * 24.515**0.75 / 5.0
    for cls in "ABCD":
        assert final_plume_rise(24.515, 5.0, cls, 300.0) == pytest.approx(expected)
    assert expected == pytest.approx(47.15, abs=0.05)


def test_high_flux_regime() -> None:
    assert final_plume_rise(100.0, 4.0, "D", 300.0) == pytest.approx(38.7 * 100.0**0.6 / 4.0)
    assert final_plume_rise(100.0, 4.0, "D", 300.0) == pytest.approx(153.3, abs=0.1)


def test_regimes_nearly_meet_at_the_boundary() -> None:
    below = final_plume_rise(54.999, 1.0, "C", 300.0)
    above = final_plume_rise(55.0, 1.0, "C", 300.0)
    assert above == pytest.approx(below, rel=0.02)


def test_stable_rise_uses_the_temperature_gradient() -> None:
    s = 9.806 / 300.0 * 0.02
    expected = 2.6 * (24.515 / (3.0 * s)) ** (1.0 / 3.0)
    assert final_plume_rise(24.515, 3.0, "E", 300.0, 0.02) == pytest.approx(expected)
    assert expected == pytest.approx(60.3, abs=0.1)


def test_stable_class_needs_a_gradient() -> None:
    with pytest.raises(ValueError, match="gradient"):
        final_plume_rise(24.515, 3.0, "F", 300.0)
    with pytest.raises(ValueError, match="gradient"):
        final_plume_rise(24.515, 3.0, "F", 300.0, 0.0)


def test_gradient_is_ignored_for_unstable_classes() -> None:
    assert final_plume_rise(24.515, 5.0, "C", 300.0, 0.02) == final_plume_rise(
        24.515,
        5.0,
        "C",
        300.0,
    )


def test_zero_flux_has_no_rise() -> None:
    assert final_plume_rise(0.0, 5.0, "D", 300.0) == 0.0
    assert final_plume_rise(0.0, 3.0, "F", 300.0, 0.035) == 0.0


@pytest.mark.parametrize("cls", ["A", "D", "F"])
def test_stronger_wind_lowers_the_rise(cls: str) -> None:
    gradient = 0.035 if cls == "F" else None
    assert final_plume_rise(24.515, 6.0, cls, 300.0, gradient) < final_plume_rise(
        24.515,
        3.0,
        cls,
        300.0,
        gradient,
    )


def test_class_is_case_insensitive() -> None:
    assert final_plume_rise(24.515, 5.0, " d ", 300.0) == final_plume_rise(24.515, 5.0, "D", 300.0)


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ((-1.0, 5.0, "D", 300.0), "buoyancy_flux"),
        ((math.nan, 5.0, "D", 300.0), "buoyancy_flux"),
        ((24.0, 0.0, "D", 300.0), "wind_speed"),
        ((24.0, 5.0, "D", 0.0), "ambient_temperature"),
        ((24.0, 5.0, "G", 300.0), "stability_class"),
        ((24.0, 5.0, "AB", 300.0), "stability_class"),
        ((24.0, 5.0, "", 300.0), "stability_class"),
    ],
)
def test_rise_rejects_impossible_input(args: tuple[float, float, str, float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        final_plume_rise(*args)


def test_downwash_lowers_the_stack_when_the_gas_is_slow() -> None:
    # vs/u = 0.6 < 1.5: h' = 30 + 2 * (0.6 - 1.5) * 2 = 26.4
    assert stack_tip_downwash(30.0, 2.0, 3.0, 5.0) == pytest.approx(26.4)


@pytest.mark.parametrize(("vs", "u"), [(7.5, 5.0), (10.0, 5.0), (30.0, 2.0)])
def test_no_downwash_at_or_above_one_and_a_half_times_the_wind(vs: float, u: float) -> None:
    assert stack_tip_downwash(30.0, 2.0, vs, u) == 30.0


def test_downwash_never_goes_below_ground() -> None:
    assert stack_tip_downwash(1.0, 2.0, 3.0, 5.0) == 0.0


@pytest.mark.parametrize(
    "args",
    [
        (-1.0, 2.0, 3.0, 5.0),
        (30.0, 0.0, 3.0, 5.0),
        (30.0, 2.0, 0.0, 5.0),
        (30.0, 2.0, 3.0, 0.0),
        (math.nan, 2.0, 3.0, 5.0),
    ],
)
def test_downwash_rejects_impossible_input(args: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        stack_tip_downwash(*args)
