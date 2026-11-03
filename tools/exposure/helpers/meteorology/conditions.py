"""Representative meteorological conditions at a point, with a labelled default on failure."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, timedelta

from commons.units import convert
from config.meteorology import MeteorologySettings, YearWindow
from models.weather.meteorology import HourlyInputs, HourlySummary, summarize_hours
from tools.exposure.helpers.inputs import point_problem
from tools.exposure.helpers.meteorology.openmeteo import ArchiveError, fetch_hourly
from tools.http import RetryingClient
from tools.schemas import Meteorology

DEFAULT_SOURCE = "screening default"


def screening_default(settings: MeteorologySettings, reason: str) -> Meteorology:
    """Return the configured default conditions, labelled, with the reason as a warning."""
    default = settings.screening_default
    return Meteorology(
        wind_speed=default.wind_speed,
        wind_direction=default.wind_direction,
        stability_class=default.stability_class,
        ambient_temperature=default.ambient_temperature,
        source=DEFAULT_SOURCE,
        warnings=[f"{reason}; using the {DEFAULT_SOURCE} (generic, not site-specific)"],
    )


def _year_problem(year: object, window: YearWindow, today: date) -> str | None:
    if isinstance(year, bool) or not isinstance(year, int):
        return f"reporting year {year!r} is invalid: it must be a whole number"
    last = (today - timedelta(days=window.archive_lag_days)).year
    if date(year, 12, 31) > today - timedelta(days=window.archive_lag_days):
        last -= 1
    if year < window.first_year or year > last:
        return (
            f"reporting year {year} is not available: "
            f"the archive covers {window.first_year} to {last}"
        )
    return None


def input_problem(
    latitude: object,
    longitude: object,
    year: object,
    window: YearWindow,
    today: date,
) -> str | None:
    """Return why the request cannot be made, or None when the inputs are valid."""
    return point_problem(latitude, longitude) or _year_problem(year, window, today)


def meteorology_for(
    latitude: float,
    longitude: float,
    reporting_year: int | None,
    settings: MeteorologySettings,
    client: RetryingClient,
    aliases: Mapping[str, str] | None,
    today: date,
) -> Meteorology:
    """Return the representative conditions at a point for a year.

    Args:
        latitude: Decimal degrees, positive north.
        longitude: Decimal degrees, positive east.
        reporting_year: Calendar year, or None for the configured default.
        settings: Archive request, year window, summary rules and screening default.
        client: Throttled, retrying HTTP client (injected).
        aliases: Unit spelling -> Pint-parsable unit string.
        today: Today's date (injected), used to find the latest complete year.

    Returns:
        Wind speed (m/s), prevailing direction (degrees), modal stability class and mean
        ambient temperature (K) with the source and any warnings; the labelled screening
        default (with the reason) when the inputs are invalid or the archive gives nothing
        usable. Data and network problems never raise.

    Raises:
        ValueError: If the configuration is unusable (a unit that cannot be converted).
    """
    year = settings.years.default_year if reporting_year is None else reporting_year
    problem = input_problem(latitude, longitude, year, settings.years, today)
    if problem is not None:
        return screening_default(settings, problem)
    try:
        data = fetch_hourly(latitude, longitude, year, settings.request, client)
    except ArchiveError as exc:
        return screening_default(settings, f"meteorological data unavailable: {exc}")
    if data.total == data.excluded:
        return screening_default(settings, f"no usable hourly data were found for {year}")
    return _summary_result(data.hours, data.excluded, year, settings, aliases)


def _temperature_k(
    mean: float,
    settings: MeteorologySettings,
    aliases: Mapping[str, str] | None,
    warnings: list[str],
) -> float:
    """Convert the mean temperature to K once (an offset unit), or use the default's."""
    if math.isnan(mean):
        warnings.append("the archive gave no temperature; using the default ambient temperature")
        return settings.screening_default.ambient_temperature
    return convert(mean, settings.request.units["temperature"], "K", aliases)


def _notes(summary: HourlySummary, excluded: int, minimum: float) -> list[str]:
    notes: list[str] = []
    if excluded:
        total = summary.hours + excluded
        notes.append(
            f"{excluded} of {total} hours were left out: a value was missing or impossible",
        )
    if summary.mean_wind_speed < minimum:
        notes.append(
            f"the mean wind speed {summary.mean_wind_speed:.2f} m/s is below the minimum; "
            f"{minimum:g} m/s is reported",
        )
    return notes


def _summary_result(
    hours: HourlyInputs,
    excluded: int,
    year: int,
    settings: MeteorologySettings,
    aliases: Mapping[str, str] | None,
) -> Meteorology:
    rules = settings.summary
    summary = summarize_hours(
        hours,
        minimum_wind_speed=rules.minimum_wind_speed,
        sector_width=rules.sector_width,
    )
    warnings = _notes(summary, excluded, rules.minimum_wind_speed)
    temperature = _temperature_k(summary.temperature, settings, aliases, warnings)
    return Meteorology(
        wind_speed=round(summary.wind_speed, 2),
        wind_direction=round(summary.wind_direction, 1),
        stability_class=summary.stability_class,
        ambient_temperature=round(temperature, 2),
        source=f"Open-Meteo {settings.request.model} reanalysis {year}",
        warnings=warnings,
    )
