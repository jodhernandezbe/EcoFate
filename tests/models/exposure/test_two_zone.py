"""Tests for the near-field / far-field inhalation model."""

from __future__ import annotations

import math

import pytest

from models.exposure.two_zone import NearField, Room, two_zone_averages

NEAR = NearField(length_m=3.05, width_m=3.05, height_m=1.83, air_speed_m_per_h=360.0)
SMALL = Room(volume_m3=300.0, air_exchange_per_h=2.0)
LARGE = Room(volume_m3=2000.0, air_exchange_per_h=15.0)


def _flows(near: NearField, room: Room) -> tuple[float, float, float]:
    sides = 2 * near.length_m * near.height_m + 2 * near.width_m * near.height_m
    q_nf = 0.5 * (sides + near.length_m * near.width_m) * near.air_speed_m_per_h
    v_nf = near.length_m * near.width_m * near.height_m
    return q_nf, room.volume_m3 * room.air_exchange_per_h, v_nf


def _integrated(g_mg_per_h: float, hours: float, room: Room) -> tuple[float, float]:
    """Independent check: integrate the two mass balances numerically from zero."""
    q_nf, q_ff, v_nf = _flows(NEAR, room)
    steps = 20_000
    dt = hours / steps
    c_nf = c_ff = total_nf = total_ff = 0.0
    for _ in range(steps):
        d_nf = (g_mg_per_h + q_nf * c_ff - q_nf * c_nf) / v_nf
        d_ff = (q_nf * c_nf - (q_nf + q_ff) * c_ff) / room.volume_m3
        total_nf, total_ff = total_nf + c_nf * dt, total_ff + c_ff * dt
        c_nf, c_ff = c_nf + d_nf * dt, c_ff + d_ff * dt
    return total_nf / hours, total_ff / hours


def test_matches_numerical_integration() -> None:
    result = two_zone_averages(1.0, 1.0, NEAR, SMALL)
    near, far = _integrated(3.6e6, 1.0, SMALL)
    assert result.near_field_mg_per_m3 == pytest.approx(near, rel=1e-3)
    assert result.far_field_mg_per_m3 == pytest.approx(far, rel=1e-3)


def test_long_activity_tends_to_steady_state() -> None:
    q_nf, q_ff, _ = _flows(NEAR, SMALL)
    result = two_zone_averages(1.0, 10_000.0, NEAR, SMALL)
    assert result.near_field_mg_per_m3 == pytest.approx(3.6e6 * (1 / q_ff + 1 / q_nf), rel=1e-3)
    assert result.far_field_mg_per_m3 == pytest.approx(3.6e6 / q_ff, rel=1e-3)


def test_near_field_is_higher() -> None:
    result = two_zone_averages(0.01, 1.0, NEAR, LARGE)
    assert result.near_field_mg_per_m3 > result.far_field_mg_per_m3


def test_proportional_to_generation() -> None:
    one = two_zone_averages(0.01, 1.0, NEAR, LARGE)
    two = two_zone_averages(0.02, 1.0, NEAR, LARGE)
    assert two.near_field_mg_per_m3 == pytest.approx(2 * one.near_field_mg_per_m3)
    assert two.far_field_mg_per_m3 == pytest.approx(2 * one.far_field_mg_per_m3)


def test_zero_generation() -> None:
    result = two_zone_averages(0.0, 1.0, NEAR, LARGE)
    assert (result.near_field_mg_per_m3, result.far_field_mg_per_m3) == (0.0, 0.0)


def test_small_room_is_worse() -> None:
    small = two_zone_averages(0.01, 1.0, NEAR, SMALL)
    assert (
        small.near_field_mg_per_m3 > two_zone_averages(0.01, 1.0, NEAR, LARGE).near_field_mg_per_m3
    )


@pytest.mark.parametrize(
    ("generation", "hours", "room"),
    [
        (math.nan, 1.0, LARGE),
        (-0.1, 1.0, LARGE),
        (0.01, -1.0, LARGE),
        (0.01, 0.0, LARGE),
        (0.01, 1.0, Room(volume_m3=0.0, air_exchange_per_h=2.0)),
        (0.01, 1.0, Room(volume_m3=300.0, air_exchange_per_h=math.inf)),
    ],
)
def test_invalid_input(generation: float, hours: float, room: Room) -> None:
    with pytest.raises(ValueError):
        two_zone_averages(generation, hours, NEAR, room)
