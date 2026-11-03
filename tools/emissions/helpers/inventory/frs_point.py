"""Recover facility coordinates from the FRS best-pick lookup when TRI has none."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence

from config.frs_point import FrsPointSettings
from tools.digits import digit_string
from tools.emissions.helpers.efservice import EfserviceClient, EfserviceError, Row
from tools.emissions.helpers.inventory.reduce import Location

logger = logging.getLogger(__name__)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _point(row: Row, settings: FrsPointSettings) -> Location | None:
    latitude = _number(row.get(settings.latitude_field))
    longitude = _number(row.get(settings.longitude_field))
    if latitude is None or longitude is None:
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return Location(latitude, longitude)


class FrsLocator:
    """Looks up the coordinates of FRS facilities in bulk, remembering answers.

    One request answers up to ``batch_size`` facilities. A failed request or an unusable
    answer leaves those facilities out of the result (and remembered as unknown), never an
    exception, so they are simply reported as without coordinates.
    """

    def __init__(self, client: EfserviceClient, settings: FrsPointSettings) -> None:
        """Args: client for the FRS service (injected); the ``[frs_point]`` settings."""
        self._client = client
        self._settings = settings
        self._known: dict[str, Location | None] = {}

    def __call__(self, frs_ids: Sequence[str]) -> Mapping[str, Location]:
        """Return the coordinates found, keyed by the FRS IDs as given."""
        digits = {frs_id: digit_string(frs_id) for frs_id in frs_ids}
        unknown = [d for d in dict.fromkeys(digits.values()) if d and d not in self._known]
        size = self._settings.batch_size
        for start in range(0, len(unknown), size):
            self._fetch(unknown[start : start + size])
        found = {frs_id: self._known.get(d or "") for frs_id, d in digits.items()}
        return {frs_id: point for frs_id, point in found.items() if point is not None}

    def _fetch(self, batch: list[str]) -> None:
        self._known.update(dict.fromkeys(batch))  # unknown until an answer says otherwise
        path = self._settings.path.format(frs_ids=",".join(batch))
        try:
            rows = self._client.get_rows(path)
        except EfserviceError as exc:
            logger.warning(
                "FRS coordinates for %d facilities could not be read: %s",
                len(batch),
                exc,
            )
            return
        for row in rows:
            raw = row.get(self._settings.registry_field)
            registry = digit_string(raw) if isinstance(raw, str | int) else None
            point = _point(row, self._settings)
            # Only an ID that was asked for, and only the first usable point of it, is kept.
            if registry is not None and registry in self._known and point is not None:
                self._known[registry] = self._known[registry] or point
