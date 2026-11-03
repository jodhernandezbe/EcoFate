"""Briggs buoyant plume rise and stack-tip downwash, as in EPA's screening procedures.

Source: U.S. EPA (1992), Screening Procedures for Estimating the Air Quality Impact of
Stationary Sources, Revised, EPA-454/R-92-019, section 4.2 (equations 4.1, 4.2, 4.6, 4.7),
which follow Briggs (1969, 1975).
"""

from __future__ import annotations

import math

GRAVITY_M_PER_S2 = 9.806  # acceleration due to gravity, as used by EPA (m/s^2)
STABLE_CLASSES = ("E", "F")
_FLUX_REGIME_BOUNDARY = 55.0  # m^4/s^3: below it the 3/4-power law applies
_LOW_FLUX_COEFFICIENT = 21.4
_HIGH_FLUX_COEFFICIENT = 38.7
_STABLE_COEFFICIENT = 2.6
_DOWNWASH_RATIO = 1.5  # downwash when exit velocity < 1.5 x wind speed at the stack
_DOWNWASH_FACTOR = 2.0


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite, positive number, got {value!r}")


def buoyancy_flux(
    exit_velocity_m_per_s: float,
    stack_diameter_m: float,
    stack_temperature_k: float,
    ambient_temperature_k: float,
) -> float:
    """Buoyancy flux Fb = g vs ds^2 (Ts - Ta) / (4 Ts) (EPA equation 4.1).

    Args:
        exit_velocity_m_per_s: Stack gas exit velocity, in meters per second (m/s); > 0.
        stack_diameter_m: Stack inside diameter, in meters (m); > 0.
        stack_temperature_k: Stack gas exit temperature, in kelvin (K); > 0.
        ambient_temperature_k: Ambient air temperature, in kelvin (K); > 0.

    Returns:
        Buoyancy flux in m^4/s^3; zero when the gas is not warmer than the air (no buoyancy).

    Raises:
        ValueError: If an argument is not finite or not positive.
    """
    for value, name in (
        (exit_velocity_m_per_s, "exit_velocity_m_per_s"),
        (stack_diameter_m, "stack_diameter_m"),
        (stack_temperature_k, "stack_temperature_k"),
        (ambient_temperature_k, "ambient_temperature_k"),
    ):
        _positive(value, name)
    excess = stack_temperature_k - ambient_temperature_k
    if excess <= 0:
        return 0.0
    return (
        GRAVITY_M_PER_S2
        * exit_velocity_m_per_s
        * stack_diameter_m**2
        * excess
        / (4.0 * stack_temperature_k)
    )


def final_plume_rise(
    buoyancy_flux_m4_per_s3: float,
    wind_speed_m_per_s: float,
    stability_class: str,
    ambient_temperature_k: float,
    potential_temperature_gradient_k_per_m: float | None = None,
) -> float:
    """Final buoyant plume rise above the stack top.

    Unstable and neutral (A to D): dh = 21.4 Fb^(3/4) / u for Fb < 55, else 38.7 Fb^(3/5) / u
    (EPA equation 4.2). Stable (E, F): dh = 2.6 (Fb / (u s))^(1/3) with s = (g / Ta) d(theta)/dz
    (EPA equation 4.6).

    Args:
        buoyancy_flux_m4_per_s3: Buoyancy flux, in m^4/s^3; >= 0.
        wind_speed_m_per_s: Wind speed at the stack top, in meters per second (m/s); > 0.
        stability_class: Pasquill-Gifford class "A" to "F".
        ambient_temperature_k: Ambient air temperature, in kelvin (K); > 0.
        potential_temperature_gradient_k_per_m: d(theta)/dz, in kelvin per meter (K/m); > 0.
            Required for a stable class, ignored otherwise.

    Returns:
        Plume rise in meters (m); zero for zero buoyancy flux.

    Raises:
        ValueError: If the class is unknown, a value is not positive, or the gradient is
            missing for a stable class.
    """
    cls = _stability_class(stability_class)
    _positive(wind_speed_m_per_s, "wind_speed_m_per_s")
    _positive(ambient_temperature_k, "ambient_temperature_k")
    flux = _flux(buoyancy_flux_m4_per_s3)
    if flux == 0:
        return 0.0
    if cls in STABLE_CLASSES:
        return _stable_rise(
            flux,
            wind_speed_m_per_s,
            ambient_temperature_k,
            potential_temperature_gradient_k_per_m,
        )
    if flux < _FLUX_REGIME_BOUNDARY:
        return _LOW_FLUX_COEFFICIENT * flux**0.75 / wind_speed_m_per_s
    return _HIGH_FLUX_COEFFICIENT * flux**0.6 / wind_speed_m_per_s


def _stability_class(stability_class: str) -> str:
    """The class as one upper-case letter A to F."""
    cls = stability_class.strip().upper()
    if cls not in "ABCDEF" or len(cls) != 1:
        raise ValueError(f"stability_class must be one of A-F, got {stability_class!r}")
    return cls


def _flux(flux: float) -> float:
    """The buoyancy flux, in m^4/s^3: a finite number that is not negative."""
    if isinstance(flux, bool) or not math.isfinite(flux) or flux < 0:
        raise ValueError(f"buoyancy_flux_m4_per_s3 must be finite and >= 0, got {flux!r}")
    return flux


def _stable_rise(
    flux: float,
    wind: float,
    ambient_k: float,
    gradient: float | None,
) -> float:
    if gradient is None:
        raise ValueError("potential_temperature_gradient_k_per_m is required for a stable class")
    _positive(gradient, "potential_temperature_gradient_k_per_m")
    stability_parameter = GRAVITY_M_PER_S2 / ambient_k * gradient  # s, in 1/s^2
    return _STABLE_COEFFICIENT * (flux / (wind * stability_parameter)) ** (1.0 / 3.0)


def stack_tip_downwash(
    stack_height_m: float,
    stack_diameter_m: float,
    exit_velocity_m_per_s: float,
    wind_speed_m_per_s: float,
) -> float:
    """Stack height corrected for stack-tip downwash (EPA equation 4.7, Briggs 1973).

    When vs < 1.5 u the plume is drawn down behind the stack: h' = hs + 2 (vs/u - 1.5) ds.
    Otherwise the height is unchanged. The result is never below zero.

    Args:
        stack_height_m: Physical stack height, in meters (m); >= 0.
        stack_diameter_m: Stack inside diameter, in meters (m); > 0.
        exit_velocity_m_per_s: Stack gas exit velocity, in meters per second (m/s); > 0.
        wind_speed_m_per_s: Wind speed at the stack top, in meters per second (m/s); > 0.

    Returns:
        Corrected stack height in meters (m).

    Raises:
        ValueError: If a value is not finite, the height is negative or another is not positive.
    """
    if isinstance(stack_height_m, bool) or not math.isfinite(stack_height_m) or stack_height_m < 0:
        raise ValueError(f"stack_height_m must be finite and >= 0, got {stack_height_m!r}")
    _positive(stack_diameter_m, "stack_diameter_m")
    _positive(exit_velocity_m_per_s, "exit_velocity_m_per_s")
    _positive(wind_speed_m_per_s, "wind_speed_m_per_s")
    ratio = exit_velocity_m_per_s / wind_speed_m_per_s
    if ratio >= _DOWNWASH_RATIO:
        return stack_height_m
    return max(
        0.0,
        stack_height_m + _DOWNWASH_FACTOR * (ratio - _DOWNWASH_RATIO) * stack_diameter_m,
    )
