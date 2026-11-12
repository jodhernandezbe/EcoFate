"""Vapor generation rate of a worker activity, and the saturation concentration of a chemical.

Source: U.S. EPA, ChemSTEER User Guide (updated May 2015): the EPA/OAQPS AP-42 Loading Model
(p. 161-167, from the CEB Engineering Manual, 1991, Eq. 4-21), the EPA/OPPT Penetration Model
(p. 174-180, CEB Manual Eq. 4-24) and the EPA/OPPT Mass Transfer Coefficient Model (p. 168-173,
Arnold and Engel, 1999), and the saturation limit of the EPA/OPPT Mass Balance Inhalation Model
(p. 274-281). Every constant is the value printed there; the units are the guide's.
"""

from __future__ import annotations

import math

CM3_PER_GALLON = 3785.4
GAS_CONSTANT_ATM_CM3 = 82.05  # atm cm^3 / (mol K)
TORR_PER_ATM = 760.0
SECONDS_PER_HOUR = 3600.0
AIR_MOLAR_MASS = 29.0  # g/mol, in the (1/29 + 1/MW) term
PENETRATION_MAX_FT_PER_MIN = 100.0  # the penetration model is for air speeds at or below this
PPM = 1.0e6


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def _positive(value: float, name: str) -> None:
    _finite(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")


def _non_negative(value: float, name: str) -> None:
    _finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value!r}")


def _fraction(value: float, name: str) -> None:
    _positive(value, name)
    if value > 1.0:
        raise ValueError(f"{name} must be at most 1, got {value!r}")


def _chemical(molecular_weight: float, vapor_pressure_torr: float, correction: float) -> None:
    _positive(molecular_weight, "molecular_weight")
    _non_negative(vapor_pressure_torr, "vapor_pressure_torr")
    _fraction(correction, "correction")


def loading_rate(
    saturation_factor: float,
    molecular_weight: float,
    container_gallons: float,
    fill_rate_per_hour: float,
    vapor_pressure_torr: float,
    temperature_k: float,
    correction: float = 1.0,
) -> float:
    """Vapor generation while filling containers (EPA/OAQPS AP-42 Loading Model).

    G = f x MW x (3785.4 x Vc) x r x X x (VP / 760) / (3600 x T x R), R = 82.05 atm cm^3/(mol K).

    Args:
        saturation_factor: f, unitless, in (0, 1].
        molecular_weight: MW, g/mol; > 0.
        container_gallons: Container volume Vc, gal; > 0.
        fill_rate_per_hour: Fill rate r, containers/h; > 0.
        vapor_pressure_torr: Vapor pressure of the pure chemical VP, torr; >= 0.
        temperature_k: T, K; > 0.
        correction: Vapor pressure correction factor X (mole fraction), unitless, in (0, 1].

    Returns:
        Vapor generation rate G, g/s.

    Raises:
        ValueError: If an input is not finite or out of its range.
    """
    _fraction(saturation_factor, "saturation_factor")
    _chemical(molecular_weight, vapor_pressure_torr, correction)
    for name, value in (
        ("container_gallons", container_gallons),
        ("fill_rate_per_hour", fill_rate_per_hour),
        ("temperature_k", temperature_k),
    ):
        _positive(value, name)
    displaced_cm3_per_s = CM3_PER_GALLON * container_gallons * fill_rate_per_hour / SECONDS_PER_HOUR
    atm = correction * vapor_pressure_torr / TORR_PER_ATM
    moles_per_cm3 = atm / (GAS_CONSTANT_ATM_CM3 * temperature_k)
    return saturation_factor * molecular_weight * displaced_cm3_per_s * moles_per_cm3


def _surface(diameter_cm: float, air_speed_ft_per_min: float, temperature_k: float) -> float:
    for name, value in (
        ("diameter_cm", diameter_cm),
        ("air_speed_ft_per_min", air_speed_ft_per_min),
        ("temperature_k", temperature_k),
    ):
        _positive(value, name)
    return math.pi * diameter_cm**2 / 4.0


def penetration_rate(
    molecular_weight: float,
    vapor_pressure_torr: float,
    air_speed_ft_per_min: float,
    diameter_cm: float,
    temperature_k: float,
    pressure_atm: float = 1.0,
    correction: float = 1.0,
) -> float:
    """Evaporation from an open liquid surface in still air (EPA/OPPT Penetration Model).

    G = 8.24e-8 x MW^0.835 x X x VP x (1/29 + 1/MW)^0.25 x vz^0.5 x A / (T^0.05 x d^0.5 x P^0.5),
    with A = pi x d^2 / 4. For air speeds at or below 100 ft/min.

    Args:
        molecular_weight: MW, g/mol; > 0.
        vapor_pressure_torr: VP, torr; >= 0.
        air_speed_ft_per_min: vz, ft/min; in (0, 100].
        diameter_cm: Diameter of the pool or opening d, cm; > 0.
        temperature_k: T, K; > 0.
        pressure_atm: Ambient pressure P, atm; > 0.
        correction: X, unitless, in (0, 1].

    Returns:
        Vapor generation rate G, g/s.

    Raises:
        ValueError: If an input is invalid or the air speed is above 100 ft/min.
    """
    _chemical(molecular_weight, vapor_pressure_torr, correction)
    area = _surface(diameter_cm, air_speed_ft_per_min, temperature_k)
    _positive(pressure_atm, "pressure_atm")
    if air_speed_ft_per_min > PENETRATION_MAX_FT_PER_MIN:
        raise ValueError("the penetration model is for air speeds at or below 100 ft/min")
    top = 8.24e-8 * molecular_weight**0.835 * correction * vapor_pressure_torr
    top *= (1.0 / AIR_MOLAR_MASS + 1.0 / molecular_weight) ** 0.25
    top *= math.sqrt(air_speed_ft_per_min) * area
    return top / (temperature_k**0.05 * math.sqrt(diameter_cm) * math.sqrt(pressure_atm))


def mass_transfer_rate(
    molecular_weight: float,
    vapor_pressure_torr: float,
    air_speed_ft_per_min: float,
    diameter_cm: float,
    temperature_k: float,
    correction: float = 1.0,
) -> float:
    """Evaporation from an open liquid surface in moving air (EPA/OPPT Mass Transfer Coefficient).

    G = 1.93e-7 x MW^0.78 x X x VP x (1/29 + 1/MW)^0.33 x vz^0.78 x A
        / (T^0.4 x d^0.11 x (T^0.5 - 5.87)^(2/3)), with A = pi x d^2 / 4. For air speeds above
    100 ft/min.

    Args:
        molecular_weight: MW, g/mol; > 0.
        vapor_pressure_torr: VP, torr; >= 0.
        air_speed_ft_per_min: vz, ft/min; > 100.
        diameter_cm: d, cm; > 0.
        temperature_k: T, K; > 0 and with T^0.5 above 5.87.
        correction: X, unitless, in (0, 1].

    Returns:
        Vapor generation rate G, g/s.

    Raises:
        ValueError: If an input is invalid or the air speed is at or below 100 ft/min.
    """
    _chemical(molecular_weight, vapor_pressure_torr, correction)
    area = _surface(diameter_cm, air_speed_ft_per_min, temperature_k)
    if air_speed_ft_per_min <= PENETRATION_MAX_FT_PER_MIN:
        raise ValueError("the mass transfer coefficient model is for air speeds above 100 ft/min")
    if math.sqrt(temperature_k) <= 5.87:
        raise ValueError("temperature_k is outside the range of the mass transfer correlation")
    top = 1.93e-7 * molecular_weight**0.78 * correction * vapor_pressure_torr
    top *= (1.0 / AIR_MOLAR_MASS + 1.0 / molecular_weight) ** 0.33
    top *= air_speed_ft_per_min**0.78 * area
    bottom = temperature_k**0.4 * diameter_cm**0.11 * (math.sqrt(temperature_k) - 5.87) ** (2 / 3)
    return top / bottom


def saturation_concentration(
    molecular_weight: float,
    vapor_pressure_torr: float,
    molar_volume_l_per_mol: float,
    correction: float = 1.0,
) -> float:
    """Saturation concentration of the chemical in air, the ceiling of any vapor concentration.

    C_sat = 1e6 x X x VP / 760 (ppm) x MW / Vm.

    Args:
        molecular_weight: MW, g/mol; > 0.
        vapor_pressure_torr: VP, torr; >= 0.
        molar_volume_l_per_mol: Vm, L/mol; > 0 (24.45 at 25 degC and 1 atm).
        correction: X, unitless, in (0, 1].

    Returns:
        Saturation concentration, mg/m^3.

    Raises:
        ValueError: If an input is invalid.
    """
    _chemical(molecular_weight, vapor_pressure_torr, correction)
    _positive(molar_volume_l_per_mol, "molar_volume_l_per_mol")
    ppm = PPM * correction * vapor_pressure_torr / TORR_PER_ATM
    return ppm * molecular_weight / molar_volume_l_per_mol
