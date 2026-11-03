"""Tests for models.transport.screening: the SCREEN3-style worst case over weather and distance."""

from __future__ import annotations

import math

import numpy as np
import pytest

from config.exposure import load_exposure_settings
from models.transport.dispersion import calculate_dispersion_coefficients
from models.transport.screening import (
    MAX_DISTANCE_M,
    MIN_DISTANCE_M,
    Atmosphere,
    Stack,
    centerline_concentrations,
    concentration_at_distance,
    effective_release_height,
    screening_maximum,
)

SETTINGS = load_exposure_settings()
COMBINATIONS = SETTINGS.combinations
DISTANCES = SETTINGS.distances_m
ATMOSPHERE = Atmosphere(SETTINGS.wind_exponent, SETTINGS.potential_temperature_gradient, 293.0, 0.0)
STACK = Stack(height_m=30.0, diameter_m=2.0, exit_velocity_m_per_s=10.0, exit_temperature_k=400.0)
Q = 100.0  # g/s


def test_ground_release_matches_the_closed_form() -> None:
    """With no height and no rise, C = Q / (pi u sigma_y sigma_z): the ground-reflected plume."""
    stack = Stack(0.0, 2.0, 30.0, 293.0)  # fast and not warm: no downwash, no buoyancy
    values, wind, height = centerline_concentrations(Q, stack, "D", 5.0, [1000.0], ATMOSPHERE)
    sigma_y, sigma_z = calculate_dispersion_coefficients(1000.0, "D")
    assert (wind, height) == (5.0, 0.0)
    assert float(values[0]) == pytest.approx(Q * 1e6 / (math.pi * 5.0 * sigma_y * sigma_z))


def test_the_default_grid_and_distances_are_screen3s() -> None:
    assert len(COMBINATIONS) == 54
    assert len(DISTANCES) == 44
    assert (DISTANCES[0], DISTANCES[-1]) == (MIN_DISTANCE_M, MAX_DISTANCE_M)


def test_the_maximum_is_attained_and_nothing_exceeds_it() -> None:
    result = screening_maximum(Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    at_result, _, _ = centerline_concentrations(
        Q,
        STACK,
        result.stability_class,
        result.wind_speed_10m_m_per_s,
        DISTANCES,
        ATMOSPHERE,
    )
    assert result.concentration_ug_per_m3 == pytest.approx(
        float(at_result[DISTANCES.index(result.distance_m)]),
    )
    brute = max(
        float(np.max(centerline_concentrations(Q, STACK, cls, u, DISTANCES, ATMOSPHERE)[0]))
        for cls, u in COMBINATIONS
    )
    assert result.concentration_ug_per_m3 == pytest.approx(brute)
    assert result.concentration_ug_per_m3 > 0


def test_the_result_describes_where_it_occurs() -> None:
    result = screening_maximum(Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    assert result.stability_class in "ABCDEF"
    assert (result.stability_class, result.wind_speed_10m_m_per_s) in COMBINATIONS
    assert MIN_DISTANCE_M <= result.distance_m <= MAX_DISTANCE_M
    assert result.effective_release_height_m >= 0
    assert result.wind_speed_stack_m_per_s >= result.wind_speed_10m_m_per_s


def test_linear_in_the_emission_rate() -> None:
    one = screening_maximum(Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    two = screening_maximum(2 * Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    assert two.concentration_ug_per_m3 == pytest.approx(2 * one.concentration_ug_per_m3)
    assert (two.stability_class, two.wind_speed_10m_m_per_s, two.distance_m) == (
        one.stability_class,
        one.wind_speed_10m_m_per_s,
        one.distance_m,
    )


def test_zero_emission_gives_zero() -> None:
    assert (
        screening_maximum(0.0, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE).concentration_ug_per_m3
        == 0.0
    )


@pytest.mark.parametrize("taller", [60.0, 120.0])
def test_a_taller_stack_does_not_raise_the_maximum(taller: float) -> None:
    base = screening_maximum(Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    higher = screening_maximum(
        Q,
        Stack(taller, 2.0, 10.0, 400.0),
        COMBINATIONS,
        DISTANCES,
        ATMOSPHERE,
    )
    assert higher.concentration_ug_per_m3 <= base.concentration_ug_per_m3


def test_a_hotter_plume_does_not_raise_the_maximum() -> None:
    cool = screening_maximum(Q, Stack(30.0, 2.0, 10.0, 300.0), COMBINATIONS, DISTANCES, ATMOSPHERE)
    hot = screening_maximum(Q, Stack(30.0, 2.0, 10.0, 600.0), COMBINATIONS, DISTANCES, ATMOSPHERE)
    assert hot.concentration_ug_per_m3 <= cool.concentration_ug_per_m3


def test_only_the_requested_distances_are_considered() -> None:
    subset = [2000.0, 3000.0]
    result = screening_maximum(Q, STACK, COMBINATIONS, subset, ATMOSPHERE)
    assert result.distance_m in subset
    full = screening_maximum(Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    assert result.concentration_ug_per_m3 <= full.concentration_ug_per_m3


def test_a_single_combination_is_the_best_of_its_own_distances() -> None:
    result = screening_maximum(Q, STACK, [("D", 5.0)], DISTANCES, ATMOSPHERE)
    values, _, _ = centerline_concentrations(Q, STACK, "D", 5.0, DISTANCES, ATMOSPHERE)
    assert result.concentration_ug_per_m3 == pytest.approx(float(np.max(values)))
    assert (result.stability_class, result.wind_speed_10m_m_per_s) == ("D", 5.0)


def test_ties_go_to_the_first_combination() -> None:
    result = screening_maximum(0.0, STACK, [("D", 5.0), ("C", 3.0)], DISTANCES, ATMOSPHERE)
    assert result.stability_class == "D"


def test_a_maximum_at_the_last_distance_is_flagged() -> None:
    tall_hot = Stack(5.0, 4.0, 20.0, 900.0)  # a very high effective height: the peak is far away
    far = screening_maximum(Q, tall_hot, [("F", 1.0)], DISTANCES, ATMOSPHERE)
    near = screening_maximum(Q, Stack(0.0, 2.0, 30.0, 293.0), [("D", 5.0)], DISTANCES, ATMOSPHERE)
    assert far.at_last_distance is True
    assert near.at_last_distance is False


def test_effective_height_is_stack_plus_rise() -> None:
    cold = effective_release_height(Stack(30.0, 2.0, 10.0, 293.0), 5.0, "D", ATMOSPHERE)
    warm = effective_release_height(STACK, 5.0, "D", ATMOSPHERE)
    assert cold == 30.0  # no buoyancy, no downwash (10 >= 1.5 * 5)
    assert warm > 30.0


def test_stable_classes_use_the_temperature_gradient() -> None:
    f = effective_release_height(STACK, 3.0, "F", ATMOSPHERE)
    e = effective_release_height(STACK, 3.0, "E", ATMOSPHERE)
    assert f != e
    assert f > 30.0 and e > 30.0


@pytest.mark.parametrize(
    "distances",
    [[], [50.0], [99.9], [10_000.1], [20_000.0], [500.0, math.nan], [500.0, math.inf]],
)
def test_distances_outside_the_dispersion_models_validity_are_refused(
    distances: list[float],
) -> None:
    with pytest.raises(ValueError):
        screening_maximum(Q, STACK, COMBINATIONS, distances, ATMOSPHERE)


def test_no_extrapolation_is_possible_through_a_single_combination() -> None:
    with pytest.raises(ValueError, match="validity"):
        centerline_concentrations(Q, STACK, "D", 5.0, [50_000.0], ATMOSPHERE)


def test_empty_combinations_are_refused() -> None:
    with pytest.raises(ValueError, match="combinations"):
        screening_maximum(Q, STACK, [], DISTANCES, ATMOSPHERE)


@pytest.mark.parametrize("rate", [-1.0, math.nan, math.inf, True])
def test_impossible_emission_rates_are_refused(rate: float) -> None:
    with pytest.raises(ValueError, match="emission_rate"):
        screening_maximum(rate, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)


def test_unknown_class_is_refused() -> None:
    with pytest.raises(ValueError):
        screening_maximum(Q, STACK, [("G", 5.0)], DISTANCES, ATMOSPHERE)


def test_class_letters_are_case_insensitive() -> None:
    lower = screening_maximum(Q, STACK, [("d", 5.0)], DISTANCES, ATMOSPHERE)
    upper = screening_maximum(Q, STACK, [("D", 5.0)], DISTANCES, ATMOSPHERE)
    assert lower == upper


def test_concentration_at_a_distance_equals_the_maximum_at_its_distance_not_above_elsewhere() -> (
    None
):
    top = screening_maximum(Q, STACK, COMBINATIONS, DISTANCES, ATMOSPHERE)
    args = (Q, STACK, top.stability_class, top.wind_speed_10m_m_per_s)
    at_top = concentration_at_distance(*args, top.distance_m, ATMOSPHERE)
    assert at_top == pytest.approx(top.concentration_ug_per_m3)
    for distance in (top.distance_m * 0.5, top.distance_m * 2.0):
        if MIN_DISTANCE_M <= distance <= MAX_DISTANCE_M:
            assert concentration_at_distance(*args, distance, ATMOSPHERE) <= at_top


@pytest.mark.parametrize("distance", [0.0, 99.0, 10_001.0, math.nan, math.inf])
def test_concentration_at_a_distance_outside_the_validity_range_raises(distance: float) -> None:
    with pytest.raises(ValueError):
        concentration_at_distance(Q, STACK, "D", 3.0, distance, ATMOSPHERE)
