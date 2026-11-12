"""Near-field / far-field (two-zone) inhalation model of a worker beside an open source.

Source: U.S. EPA, ChemSTEER User Guide (updated May 2015), EPA/OPPT Near-Field/Far-Field
Inhalation Exposure Model (p. 320-323, Table B-11a), after Keil et al. (2009). The source emits
into a near-field box around the worker, which exchanges air with the far field (the room); the
far field is ventilated. Both zones start at zero; the result is the average over the activity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MG_PER_G = 1000.0
SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class NearField:
    """The box around the worker.

    Attributes:
        length_m: Length, m.
        width_m: Width, m.
        height_m: Height, m.
        air_speed_m_per_h: Indoor air speed across the box, m/h.
    """

    length_m: float
    width_m: float
    height_m: float
    air_speed_m_per_h: float


@dataclass(frozen=True)
class Room:
    """The far field.

    Attributes:
        volume_m3: Far-field volume VFF, m^3.
        air_exchange_per_h: Air exchange rate AER, 1/h.
    """

    volume_m3: float
    air_exchange_per_h: float


@dataclass(frozen=True)
class TwoZoneAverages:
    """Concentrations averaged over the activity, mg/m^3."""

    near_field_mg_per_m3: float
    far_field_mg_per_m3: float


@dataclass(frozen=True)
class _Flows:
    v_nf: float
    v_ff: float
    q_nf: float
    q_ff: float


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite, positive number, got {value!r}")


def _flows(near: NearField, room: Room) -> _Flows:
    for name, value in (
        ("length_m", near.length_m),
        ("width_m", near.width_m),
        ("height_m", near.height_m),
        ("air_speed_m_per_h", near.air_speed_m_per_h),
        ("volume_m3", room.volume_m3),
        ("air_exchange_per_h", room.air_exchange_per_h),
    ):
        _positive(value, name)
    sides = 2 * near.length_m * near.height_m + 2 * near.width_m * near.height_m
    free_surface = sides + near.length_m * near.width_m
    return _Flows(
        v_nf=near.length_m * near.width_m * near.height_m,
        v_ff=room.volume_m3,
        q_nf=0.5 * free_surface * near.air_speed_m_per_h,
        q_ff=room.volume_m3 * room.air_exchange_per_h,
    )


def _eigenvalues(f: _Flows) -> tuple[float, float]:
    y = (f.q_nf * f.v_ff + f.v_nf * (f.q_nf + f.q_ff)) / (f.v_nf * f.v_ff)
    z = 4 * f.q_nf * f.q_ff / f.v_nf / f.v_ff
    root = math.sqrt(y * y - z)
    return 0.5 * (-y + root), 0.5 * (-y - root)


def _coefficients(
    f: _Flows,
    lam: tuple[float, float],
) -> tuple[float, float, float, float, float]:
    """The intermediate parameters k1 to k5 of Table B-11a, h/m^3."""
    l1, l2 = lam
    scale = f.q_nf * f.q_ff * f.v_nf * (l1 - l2)
    k2 = (f.q_nf * f.q_ff + l2 * f.v_nf * (f.q_nf + f.q_ff)) / scale
    k3 = (f.q_nf * f.q_ff + l1 * f.v_nf * (f.q_nf + f.q_ff)) / scale
    k1 = 1.0 / ((f.q_nf / (f.q_nf + f.q_ff)) * f.q_ff)
    k4 = (l1 * f.v_nf + f.q_nf) / f.q_nf * k2
    k5 = (l2 * f.v_nf + f.q_nf) / f.q_nf * k3
    return k1, k2, k3, k4, k5


def _integral(c1: float, c2: float, lam: tuple[float, float], hours: float) -> float:
    """Integral over [0, h] of c1 x exp(l1 t) - c2 x exp(l2 t), in (h/m^3) per unit emission."""
    l1, l2 = lam
    return c1 * math.expm1(l1 * hours) / l1 - c2 * math.expm1(l2 * hours) / l2


def two_zone_averages(
    generation_g_per_s: float,
    hours: float,
    near: NearField,
    room: Room,
) -> TwoZoneAverages:
    """Near-field and far-field concentrations averaged over an activity of ``hours``.

    With G in mg/h, Q in m^3/h and V in m^3 (ChemSTEER Table B-11a):
    Cnf_TWA = G x (k1 x h + k2 (e^(l1 h) - 1) / l1 - k3 (e^(l2 h) - 1) / l2) / h and
    Cff_TWA = G x (h / QFF + k4 (e^(l1 h) - 1) / l1 - k5 (e^(l2 h) - 1) / l2) / h, where
    QNF = 0.5 x free surface area x air speed and QFF = VFF x AER.

    Args:
        generation_g_per_s: Vapor generation rate G, g/s; >= 0.
        hours: Duration of the activity h, h; > 0.
        near: The near-field box (m, m/h).
        room: The far field (m^3, 1/h).

    Returns:
        Both averages, mg/m^3.

    Raises:
        ValueError: If an input is not finite or out of its range.
    """
    if isinstance(generation_g_per_s, bool) or not math.isfinite(generation_g_per_s):
        raise ValueError(f"generation_g_per_s must be finite, got {generation_g_per_s!r}")
    if generation_g_per_s < 0:
        raise ValueError("generation_g_per_s must not be negative")
    _positive(hours, "hours")
    f = _flows(near, room)
    lam = _eigenvalues(f)
    k1, k2, k3, k4, k5 = _coefficients(f, lam)
    rate = generation_g_per_s * MG_PER_G * SECONDS_PER_HOUR
    near_avg = rate * (k1 * hours + _integral(k2, k3, lam, hours)) / hours
    far_avg = rate * (hours / f.q_ff + _integral(k4, k5, lam, hours)) / hours
    return TwoZoneAverages(near_field_mg_per_m3=near_avg, far_field_mg_per_m3=far_avg)
