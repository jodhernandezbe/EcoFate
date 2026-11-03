"""Rank the census tracts around a facility by what a scenario's own configuration gives there.

The scenario fixes the weather (stability class and 10 m wind speed), the stack and the emission
rate; the concentration is then evaluated at each tract's distance with the same equations as
the worst-case search, so a tract at the distance of the maximum has the maximum. Bearing is
reported but does not select: the screening weather has no wind direction.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.transport.screening import (
    MAX_DISTANCE_M,
    MIN_DISTANCE_M,
    Atmosphere,
    Stack,
    concentration_at_distance,
)
from tools.schemas import ScenarioReceptor, StackParameters, TractReceptor

_STACK_FIELDS = ("stack_height", "stack_diameter", "exit_velocity", "exit_temperature")


@dataclass(frozen=True)
class Weather:
    """The fixed conditions of a scenario.

    Attributes:
        stability_class: Pasquill-Gifford class.
        wind_speed_10m: Wind speed at 10 m, m/s.
        maximum: The scenario's annual-average maximum, ug/m^3.
        annual_factor: 1-hour to annual-average multiplier, unitless, in (0, 1].
    """

    stability_class: str
    wind_speed_10m: float
    maximum: float
    annual_factor: float


@dataclass(frozen=True)
class Ranked:
    """The receptors of a scenario, and what to say about them."""

    listed: list[ScenarioReceptor]
    note: str | None


def stack_of(params: StackParameters) -> Stack | None:
    """The stack in SI units, or None when a value is missing or not positive."""
    values = [params.get(name) for name in _STACK_FIELDS]
    if any(not isinstance(v, int | float) or isinstance(v, bool) or v <= 0 for v in values):
        return None
    height, diameter, velocity, temperature = (float(v) for v in values)  # type: ignore[arg-type]
    return Stack(height, diameter, velocity, temperature)


def _receptor(tract: TractReceptor, concentration: float, maximum: float) -> ScenarioReceptor:
    return ScenarioReceptor(
        kind="tract",
        label=tract["geoid"],
        residents=tract["residents"],
        age_distribution=dict(tract["age_distribution"]),
        distance_m=tract["distance_m"],
        bearing_deg=tract["bearing_deg"],
        latitude=tract["latitude"],
        longitude=tract["longitude"],
        concentration=concentration,
        fraction_of_maximum=concentration / maximum,
        note=None,
    )


def _evaluate(
    tracts: list[TractReceptor],
    rate: float,
    stack: Stack,
    weather: Weather,
    air: Atmosphere,
) -> tuple[list[ScenarioReceptor], int]:
    """Each tract in the model's range with its concentration, and how many were out of range."""
    found: list[ScenarioReceptor] = []
    outside = 0
    for tract in tracts:
        if not MIN_DISTANCE_M <= tract["distance_m"] <= MAX_DISTANCE_M:
            outside += 1
            continue
        one_hour = concentration_at_distance(
            rate,
            stack,
            weather.stability_class,
            weather.wind_speed_10m,
            tract["distance_m"],
            air,
        )
        found.append(_receptor(tract, one_hour * weather.annual_factor, weather.maximum))
    return found, outside


def _note(found: list[ScenarioReceptor], listed: int, outside: int, total: int) -> str | None:
    parts: list[str] = []
    if total == 0:
        return "no census tract with residents was listed around the facility"
    if outside:
        parts.append(f"{outside} tracts lie outside the model's 100 m to 10 km range")
    if not listed and found:
        near = min(found, key=lambda r: r["distance_m"] or 0.0)
        parts.append(
            "no resident lives where the maximum falls; the nearest populated tract "
            f"({near['label']}) has {near['fraction_of_maximum']:.2g} of the maximum",
        )
    elif not found:
        parts.append("no listed tract lies where the model applies")
    return "; ".join(parts) or None


def rank_tracts(
    tracts: list[TractReceptor],
    rate: float,
    stack: Stack,
    weather: Weather,
    atmosphere: Atmosphere,
    limits: tuple[float, int],
) -> Ranked:
    """The tracts most affected under a scenario, highest concentration first.

    Args:
        tracts: The tracts around the facility (residents, distance m, bearing deg).
        rate: Emission rate, g/s.
        stack: The scenario's stack.
        weather: The scenario's fixed weather and its maximum.
        atmosphere: Wind exponents, temperature gradients, ambient temperature, receptor height.
        limits: ``(fraction of the maximum a tract must reach, most tracts listed)``.

    Returns:
        The tracts at or above the fraction, up to the cap, and a note saying what is missing
        (no tracts, tracts outside the model's range, or nobody where the maximum falls).
    """
    found, outside = _evaluate(tracts, rate, stack, weather, atmosphere)
    fraction, cap = limits
    chosen = [r for r in found if (r["fraction_of_maximum"] or 0.0) >= fraction]
    chosen.sort(key=lambda r: r["concentration"] or 0.0, reverse=True)
    return Ranked(chosen[:cap], _note(found, len(chosen), outside, len(tracts)))
