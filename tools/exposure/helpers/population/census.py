"""Census tracts around a point (TIGERweb) and their ACS 5-year counts (Census Data API)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from config.population import ACS_VARIABLES, PopulationSettings
from tools.digits import digit_string
from tools.http import HttpRequestError, RetryingClient

_KEY_STATUSES = frozenset({302, 401, 403})
_NO_CONTENT = 204
_WIDTHS = {"state": 2, "county": 3, "tract": 6}
_MAX_LATITUDE = 90.0
_MAX_LONGITUDE = 180.0


class CensusError(RuntimeError):
    """The Census services did not give a usable answer; the message says why.

    Attributes:
        key_rejected: True when the Census Data API refused the API key (or none was sent).
    """

    def __init__(self, message: str, *, key_rejected: bool = False) -> None:
        """Create the error with its message and whether the key was the problem."""
        super().__init__(message)
        self.key_rejected = key_rejected


@dataclass(frozen=True)
class Tract:
    """A census tract that intersects the search circle.

    Attributes:
        state: Two-digit state FIPS code.
        county: Three-digit county FIPS code.
        tract: Six-digit tract code.
        land_area_m2: Land area, in square meters (m^2).
        latitude: Internal point latitude, decimal degrees; None when the service gave none.
        longitude: Internal point longitude, decimal degrees; None when the service gave none.
    """

    state: str
    county: str
    tract: str
    land_area_m2: float
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class Counts:
    """ACS 5-year estimates for one tract, in persons.

    Attributes:
        total: All residents.
        under_5: Residents under 5 years.
        under_18: Residents under 18 years.
        over_65: Residents 65 years and over.
    """

    total: float
    under_5: float
    under_18: float
    over_65: float


def _padded(value: object, kind: str) -> str:
    code = (
        digit_string(value)
        if isinstance(value, str | int) and not isinstance(value, bool)
        else None
    )
    if code is None or len(code) > _WIDTHS[kind]:
        raise CensusError(f"a census tract has an invalid {kind} code ({value!r})")
    return code.zfill(_WIDTHS[kind])


def _land_area(value: object) -> float:
    ok = isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    if not ok or float(value) < 0:  # type: ignore[arg-type]
        raise CensusError(f"a census tract has an invalid land area ({value!r})")
    return float(value)  # type: ignore[arg-type]


def _coordinate(value: object, limit: float) -> float | None:
    """A signed decimal-degree coordinate given as text or number, or None when unusable."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and abs(number) <= limit else None


def _tract(feature: object, fields: Mapping[str, str]) -> Tract:
    record = cast(dict[str, object], feature) if isinstance(feature, dict) else {}
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        raise CensusError("the tract service returned a record without attributes")
    row = cast(dict[str, object], attributes)
    return Tract(
        state=_padded(row.get(fields["state"]), "state"),
        county=_padded(row.get(fields["county"]), "county"),
        tract=_padded(row.get(fields["tract"]), "tract"),
        land_area_m2=_land_area(row.get(fields["land_area"])),
        latitude=_coordinate(row.get(fields["latitude"]), _MAX_LATITUDE),
        longitude=_coordinate(row.get(fields["longitude"]), _MAX_LONGITUDE),
    )


def _get(
    client: RetryingClient,
    url: str,
    params: Mapping[str, str | int | float],
    what: str,
    *,
    allow_empty: bool = False,
) -> object:
    """GET JSON; a 204 gives None when ``allow_empty``; a refused key raises ``key_rejected``."""
    try:
        return client.get_json(url, params)
    except HttpRequestError as exc:
        if allow_empty and exc.status_code == _NO_CONTENT:
            return None
        if exc.status_code in _KEY_STATUSES:
            raise CensusError(
                f"the Census API key is missing or was rejected (HTTP {exc.status_code})",
                key_rejected=True,
            ) from exc
        raise CensusError(f"{what} could not be read ({exc})") from exc


def _tract_params(
    latitude: float,
    longitude: float,
    radius_m: float,
    fields: Mapping[str, str],
) -> dict[str, str | int | float]:
    return {
        "geometry": f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": radius_m,
        "units": "esriSRUnit_Meter",
        "outFields": ",".join(fields.values()),
        "returnGeometry": "false",
        "f": "json",
    }


def _features(payload: object) -> list[object]:
    if not isinstance(payload, dict) or "error" in payload:
        raise CensusError("the tract service returned an error or an unexpected answer")
    body = cast(dict[str, object], payload)
    if body.get("exceededTransferLimit"):
        raise CensusError("the tract list is incomplete (the service reached its record limit)")
    features = body.get("features")
    if not isinstance(features, list):
        raise CensusError("the tract service answer has no list of features")
    return cast(list[object], features)


def fetch_tracts(
    latitude: float,
    longitude: float,
    radius_m: float,
    settings: PopulationSettings,
    client: RetryingClient,
) -> list[Tract]:
    """Return the census tracts that intersect a circle.

    Args:
        latitude: Center latitude, decimal degrees (already validated).
        longitude: Center longitude, decimal degrees (already validated).
        radius_m: Circle radius, in meters.
        settings: Tract service URL and field names.
        client: Throttled, retrying HTTP client (injected).

    Raises:
        CensusError: If the request fails, the answer is not the expected shape, the tract
            list is incomplete (the service reached its transfer limit), or a record is
            invalid. An empty list is a valid answer (open water or outside the US).
    """
    params = _tract_params(latitude, longitude, radius_m, settings.fields)
    payload = _get(client, settings.tract_url, params, "the census tract service")
    return [_tract(feature, settings.fields) for feature in _features(payload)]


def _estimate(cell: object) -> float | None:
    """Return an ACS cell as a count, or None if it is missing, not numeric or a negative code."""
    if isinstance(cell, bool) or not isinstance(cell, int | float | str):
        return None
    try:
        value = float(cell)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _columns(header: object, variables: Mapping[str, str]) -> dict[str, int]:
    names = cast(list[object], header) if isinstance(header, list) else []
    wanted = [*variables.values(), "tract"]
    missing = [name for name in wanted if name not in names]
    if missing:
        raise CensusError(f"the ACS answer lacks the columns {', '.join(missing)}")
    return {name: names.index(name) for name in wanted}


def _row_counts(
    row: Sequence[object],
    at: Mapping[str, int],
    variables: Mapping[str, str],
) -> Counts | None:
    values = [_estimate(row[at[variables[key]]]) for key in ACS_VARIABLES]
    if any(value is None for value in values):
        return None
    total, under_5, under_18, over_65 = (cast(float, v) for v in values)
    return Counts(total, under_5, under_18, over_65)


def fetch_counts(
    state: str,
    county: str,
    settings: PopulationSettings,
    client: RetryingClient,
    api_key: str,
) -> dict[str, Counts | None]:
    """Return the ACS counts of every tract of a county, keyed by six-digit tract code.

    Args:
        state: Two-digit state FIPS code.
        county: Three-digit county FIPS code.
        settings: ACS dataset URL and variable codes.
        client: Throttled, retrying HTTP client (injected).
        api_key: Census API key; sent as the ``key`` parameter and never logged.

    Returns:
        Tract code -> counts, or None where any estimate is missing or a negative code.
        A county with no rows gives an empty mapping.

    Raises:
        CensusError: If the key is missing or rejected (``key_rejected``), the request
            fails, or the answer is not the expected shape.
    """
    variables = settings.variables
    params = {
        "get": ",".join(variables[key] for key in ACS_VARIABLES),
        "for": "tract:*",
        "in": f"state:{state} county:{county}",
        "key": api_key,
    }
    payload = _get(client, settings.acs_url, params, "the ACS data", allow_empty=True)
    if payload is None:
        return {}
    if not isinstance(payload, list) or not payload:
        raise CensusError("the ACS answer is not a table")
    rows = cast(list[object], payload)
    at = _columns(rows[0], variables)
    table = [cast(list[object], row) for row in rows[1:] if isinstance(row, list)]
    return {_padded(row[at["tract"]], "tract"): _row_counts(row, at, variables) for row in table}
