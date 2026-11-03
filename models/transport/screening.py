"""SCREEN3-style worst case: the maximum ground-level concentration over weather and distance.

For each (stability class, 10 m wind speed) combination the wind is adjusted to the stack top,
the stack height is corrected for stack-tip downwash, the final buoyant plume rise is added, and
the ground-level centerline concentration is evaluated at every distance with the Briggs rural
dispersion coefficients and the Gaussian plume with ground reflection. The largest value over
all pairs is the screening concentration (EPA-454/B-95-004, section 3; EPA-454/R-92-019).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from models.transport.dispersion import calculate_dispersion_coefficients, gaussian_plume
from models.transport.plume_rise import (
    STABLE_CLASSES,
    buoyancy_flux,
    final_plume_rise,
    stack_tip_downwash,
)
from models.transport.wind_profile import wind_speed_at_height

MIN_DISTANCE_M = 100.0  # validity range of the Briggs open-country coefficients
MAX_DISTANCE_M = 10_000.0
_UG_PER_G = 1e6


@dataclass(frozen=True)
class Stack:
    """A point source's stack, in SI units.

    Attributes:
        height_m: Physical stack height (m); >= 0.
        diameter_m: Inside diameter (m); > 0.
        exit_velocity_m_per_s: Stack gas exit velocity (m/s); > 0.
        exit_temperature_k: Stack gas exit temperature (K); > 0.
    """

    height_m: float
    diameter_m: float
    exit_velocity_m_per_s: float
    exit_temperature_k: float


@dataclass(frozen=True)
class Atmosphere:
    """Per-class parameters of the screening atmosphere.

    Attributes:
        wind_exponent: Stability class -> wind-profile power-law exponent (unitless).
        potential_temperature_gradient: Stable class -> d(theta)/dz (K/m).
        ambient_temperature_k: Ambient air temperature (K); > 0.
        receptor_height_m: Receptor height above ground (m); >= 0.
    """

    wind_exponent: Mapping[str, float]
    potential_temperature_gradient: Mapping[str, float]
    ambient_temperature_k: float
    receptor_height_m: float = 0.0


@dataclass(frozen=True)
class ScreeningResult:
    """The worst case found and where it occurs.

    Attributes:
        concentration_ug_per_m3: Maximum 1-hour ground-level concentration (ug/m^3).
        distance_m: Downwind distance of the maximum (m).
        stability_class: Class of the worst-case combination.
        wind_speed_10m_m_per_s: 10 m wind speed of the worst-case combination (m/s).
        wind_speed_stack_m_per_s: Wind speed at the stack top for that combination (m/s).
        effective_release_height_m: Downwash-corrected stack height plus plume rise (m).
        at_last_distance: True when the maximum falls at the farthest distance evaluated.
    """

    concentration_ug_per_m3: float
    distance_m: float
    stability_class: str
    wind_speed_10m_m_per_s: float
    wind_speed_stack_m_per_s: float
    effective_release_height_m: float
    at_last_distance: bool


def effective_release_height(
    stack: Stack,
    wind_speed_stack_m_per_s: float,
    stability_class: str,
    atmosphere: Atmosphere,
) -> float:
    """Downwash-corrected stack height plus final buoyant plume rise, in meters (m)."""
    corrected = stack_tip_downwash(
        stack.height_m,
        stack.diameter_m,
        stack.exit_velocity_m_per_s,
        wind_speed_stack_m_per_s,
    )
    return corrected + _plume_rise(stack, wind_speed_stack_m_per_s, stability_class, atmosphere)


def _plume_rise(
    stack: Stack,
    wind_speed_stack_m_per_s: float,
    stability_class: str,
    atmosphere: Atmosphere,
) -> float:
    """Final buoyant plume rise above the stack top, in meters (m), for the stability class."""
    flux = buoyancy_flux(
        stack.exit_velocity_m_per_s,
        stack.diameter_m,
        stack.exit_temperature_k,
        atmosphere.ambient_temperature_k,
    )
    stable = stability_class in STABLE_CLASSES
    gradient = atmosphere.potential_temperature_gradient.get(stability_class) if stable else None
    return final_plume_rise(
        flux,
        wind_speed_stack_m_per_s,
        stability_class,
        atmosphere.ambient_temperature_k,
        gradient,
    )


def _check_distances(distances_m: Sequence[float] | np.ndarray) -> np.ndarray:
    x = np.asarray(distances_m, dtype=np.float64)
    if x.size == 0:
        raise ValueError("distances_m must not be empty")
    outside = np.any(x < MIN_DISTANCE_M) or np.any(x > MAX_DISTANCE_M)
    if not np.all(np.isfinite(x)) or outside:
        raise ValueError(
            f"every distance must be within {MIN_DISTANCE_M:g} to {MAX_DISTANCE_M:g} m, "
            "the validity range of the dispersion coefficients",
        )
    return x


def _check_emission(emission_rate_g_per_s: float) -> None:
    rate = emission_rate_g_per_s
    if isinstance(rate, bool) or not math.isfinite(rate) or rate < 0:
        raise ValueError("emission_rate_g_per_s must be finite and >= 0")


def _concentrations(
    emission_rate_g_per_s: float,
    stack: Stack,
    stability_class: str,
    wind_speed_10m_m_per_s: float,
    x: np.ndarray,
    atmosphere: Atmosphere,
) -> tuple[np.ndarray, float, float]:
    exponent = atmosphere.wind_exponent.get(stability_class)
    if exponent is None:
        raise ValueError(f"no wind exponent for stability class {stability_class!r}")
    wind_stack = wind_speed_at_height(wind_speed_10m_m_per_s, stack.height_m, exponent)
    height = effective_release_height(stack, wind_stack, stability_class, atmosphere)
    sigma_y, sigma_z = calculate_dispersion_coefficients(x, stability_class)
    grams = gaussian_plume(
        emission_rate_g_per_s,
        wind_stack,
        0.0,
        atmosphere.receptor_height_m,
        height,
        sigma_y,
        sigma_z,
    )
    return np.asarray(grams, dtype=np.float64) * _UG_PER_G, wind_stack, height


def centerline_concentrations(
    emission_rate_g_per_s: float,
    stack: Stack,
    stability_class: str,
    wind_speed_10m_m_per_s: float,
    distances_m: Sequence[float],
    atmosphere: Atmosphere,
) -> tuple[np.ndarray, float, float]:
    """Ground-level centerline concentrations at each distance for one weather combination.

    Returns:
        ``(concentrations in ug/m^3, wind speed at the stack top in m/s, effective release
        height in m)``.

    Raises:
        ValueError: If the emission rate is negative, a distance is outside the validity range,
            or a stack or atmosphere value is impossible.
    """
    _check_emission(emission_rate_g_per_s)
    return _concentrations(
        emission_rate_g_per_s,
        stack,
        stability_class.strip().upper(),
        wind_speed_10m_m_per_s,
        _check_distances(distances_m),
        atmosphere,
    )


def concentration_at_distance(
    emission_rate_g_per_s: float,
    stack: Stack,
    stability_class: str,
    wind_speed_10m_m_per_s: float,
    distance_m: float,
    atmosphere: Atmosphere,
) -> float:
    """Ground-level centerline 1-hour concentration at one distance for a fixed weather.

    The same equations as the worst-case search, evaluated at a stated distance, so at the
    distance of the worst case it equals the maximum and elsewhere it is not larger.

    Args:
        emission_rate_g_per_s: Emission rate, in grams per second (g/s); >= 0.
        stack: The stack, in SI units.
        stability_class: Pasquill-Gifford class A to F.
        wind_speed_10m_m_per_s: Wind speed at 10 m, in meters per second (m/s).
        distance_m: Downwind distance, in meters (m), within 100 to 10,000.
        atmosphere: Per-class exponents and gradients, ambient temperature, receptor height.

    Returns:
        Concentration in micrograms per cubic meter (ug/m^3).

    Raises:
        ValueError: If the emission rate, the distance or a stack or atmosphere value is
            impossible.
    """
    values, _, _ = centerline_concentrations(
        emission_rate_g_per_s,
        stack,
        stability_class,
        wind_speed_10m_m_per_s,
        [distance_m],
        atmosphere,
    )
    return float(values[0])


def screening_maximum(
    emission_rate_g_per_s: float,
    stack: Stack,
    combinations: Sequence[tuple[str, float]],
    distances_m: Sequence[float],
    atmosphere: Atmosphere,
) -> ScreeningResult:
    """Find the worst-case 1-hour concentration over weather combinations and distances.

    Args:
        emission_rate_g_per_s: Emission rate, in grams per second (g/s); >= 0.
        stack: The stack, in SI units.
        combinations: (stability class, 10 m wind speed in m/s) pairs to evaluate.
        distances_m: Downwind distances to evaluate, in meters (m), each within 100 to 10,000.
        atmosphere: Per-class exponents and gradients, ambient temperature, receptor height.

    Returns:
        The maximum and the combination, distance and release height that gave it. Ties go to
        the first combination and the shortest distance evaluated.

    Raises:
        ValueError: If the combinations or distances are empty or any input is impossible.
    """
    if not combinations:
        raise ValueError("combinations must not be empty")
    _check_emission(emission_rate_g_per_s)
    x = _check_distances(distances_m)
    results = [
        _best_at(emission_rate_g_per_s, stack, cls.strip().upper(), wind, x, atmosphere)
        for cls, wind in combinations
    ]
    return max(results, key=lambda r: r.concentration_ug_per_m3)


def _best_at(
    emission_rate_g_per_s: float,
    stack: Stack,
    stability_class: str,
    wind_speed_10m_m_per_s: float,
    x: np.ndarray,
    atmosphere: Atmosphere,
) -> ScreeningResult:
    values, wind_stack, height = _concentrations(
        emission_rate_g_per_s,
        stack,
        stability_class,
        wind_speed_10m_m_per_s,
        x,
        atmosphere,
    )
    index = int(np.argmax(values))
    return ScreeningResult(
        float(values[index]),
        float(x[index]),
        stability_class,
        wind_speed_10m_m_per_s,
        wind_stack,
        height,
        index == x.size - 1,
    )
