"""One year of hourly weather from the Open-Meteo archive, checked and masked."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray

from config.meteorology import HOURLY_QUANTITIES, ArchiveRequest
from models.weather.meteorology import HourlyInputs
from tools.http import HttpRequestError, RetryingClient

_MAX_DIRECTION = 360.0
_MAX_PERCENT = 100.0


class ArchiveError(RuntimeError):
    """The archive did not give a usable answer; the message says why."""


@dataclass(frozen=True)
class HourlyData:
    """The usable hours of one year.

    Attributes:
        hours: Hours that passed every check (temperature is NaN where it was missing).
        total: Hours the archive returned.
    """

    hours: HourlyInputs
    total: int

    @property
    def excluded(self) -> int:
        """Hours left out because a required value was missing or impossible."""
        return self.total - len(self.hours.wind_speed)


def archive_params(
    latitude: float,
    longitude: float,
    year: int,
    request: ArchiveRequest,
) -> dict[str, str | int | float]:
    """Return the query parameters asking for the whole of ``year`` at a point."""
    decimals = request.coordinate_decimals
    return {
        "latitude": round(latitude, decimals),
        "longitude": round(longitude, decimals),
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": ",".join(request.variables[q] for q in HOURLY_QUANTITIES),
        "wind_speed_unit": request.wind_speed_unit,
        "timezone": request.timezone,
        "models": request.model,
    }


def _object(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArchiveError(f"the archive response has no {what} object")
    return {str(k): v for k, v in cast(dict[object, object], value).items()}


def _one_series(
    quantity: str,
    hourly: dict[str, object],
    units: dict[str, object],
    request: ArchiveRequest,
) -> list[object]:
    name = request.variables[quantity]
    values = hourly.get(name)
    if not isinstance(values, list):
        raise ArchiveError(f"the archive response lacks the hourly series {name}")
    if units.get(name) != request.units[quantity]:
        raise ArchiveError(
            f"{name} is reported in {units.get(name)!r}, expected {request.units[quantity]!r}",
        )
    return cast(list[object], values)


def _series(payload: object, request: ArchiveRequest) -> dict[str, list[object]]:
    """Return quantity -> list, after checking presence, equal lengths and reported units."""
    body = _object(payload, "JSON")
    hourly = _object(body.get("hourly"), "hourly")
    units = _object(body.get("hourly_units"), "units")
    series = {q: _one_series(q, hourly, units, request) for q in HOURLY_QUANTITIES}
    if len({len(values) for values in series.values()}) != 1:
        raise ArchiveError("the hourly series have different lengths")
    return series


def _floats(values: Sequence[object]) -> NDArray[np.float64]:
    """Convert to floats; a missing, non-numeric, boolean or non-finite value becomes NaN."""
    clean = [
        float(v) if isinstance(v, int | float) and not isinstance(v, bool) else math.nan
        for v in values
    ]
    array = np.asarray(clean, dtype=np.float64)
    array[~np.isfinite(array)] = math.nan
    return array


def _within(values: NDArray[np.float64], low: float, high: float | None) -> NDArray[np.bool_]:
    ok = np.isfinite(values) & (values >= low)
    return ok if high is None else ok & (values <= high)


def _valid_mask(a: dict[str, NDArray[np.float64]]) -> NDArray[np.bool_]:
    return (
        _within(a["wind_speed"], 0.0, None)
        & _within(a["wind_direction"], 0.0, _MAX_DIRECTION)
        & _within(a["solar_radiation"], 0.0, None)
        & _within(a["cloud_cover"], 0.0, _MAX_PERCENT)
        & _within(a["low_cloud_cover"], 0.0, _MAX_PERCENT)
        & np.isin(a["is_day"], (0.0, 1.0))
    )


def mask_hours(series: dict[str, list[object]]) -> HourlyData:
    """Keep the hours whose required values are present and physically possible."""
    arrays = {quantity: _floats(values) for quantity, values in series.items()}
    keep = _valid_mask(arrays)
    return HourlyData(
        hours=HourlyInputs(
            wind_speed=arrays["wind_speed"][keep],
            wind_direction=arrays["wind_direction"][keep],
            solar_radiation=arrays["solar_radiation"][keep],
            cloud_cover=arrays["cloud_cover"][keep],
            low_cloud_cover=arrays["low_cloud_cover"][keep],
            is_day=arrays["is_day"][keep] == 1.0,
            temperature=arrays["temperature"][keep],
        ),
        total=len(keep),
    )


def fetch_hourly(
    latitude: float,
    longitude: float,
    year: int,
    request: ArchiveRequest,
    client: RetryingClient,
) -> HourlyData:
    """Fetch and check one year of hourly weather at a point.

    Args:
        latitude: Decimal degrees, -90 to 90 (already validated).
        longitude: Decimal degrees, -180 to 180 (already validated).
        year: Calendar year to request (already checked against the archive's range).
        request: Archive endpoint, variables and expected units.
        client: Throttled, retrying HTTP client (injected).

    Returns:
        The hours that passed the checks (see ``HourlyData``).

    Raises:
        ArchiveError: If the request fails after its retries, the answer is not the expected
            shape, a series is missing, the series differ in length, or a unit is not the
            one asked for.
    """
    params = archive_params(latitude, longitude, year, request)
    try:
        payload = client.get_json(request.url, params)
    except HttpRequestError as exc:
        raise ArchiveError(f"the archive could not be read ({exc})") from exc
    return mask_hours(_series(payload, request))
