"""Tests for models.receptors.geometry: distance and bearing from a facility to a receptor."""

from __future__ import annotations

import math

import pytest

from models.receptors.geometry import EARTH_RADIUS_M, bearing_deg, distance_m


def test_one_degree_of_latitude_is_the_arc_of_the_radius() -> None:
    assert distance_m(10.0, 20.0, 11.0, 20.0) == pytest.approx(EARTH_RADIUS_M * math.radians(1.0))


def test_due_east_bears_90_and_due_north_0() -> None:
    assert bearing_deg(0.0, 10.0, 0.0, 11.0) == pytest.approx(90.0)
    assert bearing_deg(10.0, 10.0, 11.0, 10.0) == pytest.approx(0.0)


def test_due_west_and_south_wrap_into_the_circle() -> None:
    assert bearing_deg(0.0, 10.0, 0.0, 9.0) == pytest.approx(270.0)
    assert bearing_deg(10.0, 10.0, 9.0, 10.0) == pytest.approx(180.0)


def test_the_same_point_is_zero_distance_and_zero_bearing() -> None:
    assert distance_m(18.15, -65.96, 18.15, -65.96) == 0.0
    assert bearing_deg(18.15, -65.96, 18.15, -65.96) == 0.0


def test_distance_is_symmetric() -> None:
    assert distance_m(18.0, -65.0, 18.2, -65.3) == pytest.approx(
        distance_m(18.2, -65.3, 18.0, -65.0),
    )


@pytest.mark.parametrize("bad", [(91.0, 0.0), (0.0, 181.0), (math.nan, 0.0), (0.0, math.inf)])
def test_invalid_coordinates_raise(bad: tuple[float, float]) -> None:
    with pytest.raises(ValueError):
        distance_m(*bad, 0.0, 0.0)
    with pytest.raises(ValueError):
        bearing_deg(0.0, 0.0, *bad)


def test_a_bool_is_not_a_coordinate() -> None:
    with pytest.raises(ValueError):
        distance_m(True, 0.0, 0.0, 0.0)
