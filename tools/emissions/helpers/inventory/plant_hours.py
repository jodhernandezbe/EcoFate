"""Operating hours of a facility from the Census QPC plant-hours baseline, by NAICS code.

The baseline (``data/census_qpc_baseline.parquet``, built by
``scripts.build_census_qpc_baseline``) gives average plant hours per week by NAICS code. A
facility's code is matched against it most specific first (its own length down to
``min_digits``); the hours per week become hours per year as h/week x days_per_year / 7. With no
match, or no usable baseline, the configured default is used and the source says so.
"""

# pyarrow ships no type information, so strict mode cannot see through its objects here.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq

from commons.prefix import longest_prefix
from config.plant_hours import PlantHoursSettings
from tools.digits import digit_string
from tools.emissions.helpers.inventory.rate import OperatingHours

logger = logging.getLogger(__name__)

RELEASE_KEY = b"qpc.release"
DAYS_PER_WEEK = 7
MIN_CODE_DIGITS = 2


@dataclass(frozen=True)
class Baseline:
    """The validated baseline: hours per week (h/week) by code, and the release it is from."""

    hours_per_week: MappingProxyType[str, float]
    release: str
    warnings: tuple[str, ...]


def _empty(reason: str) -> Baseline:
    return Baseline(MappingProxyType({}), "", (reason,))


def _release(schema: pa.Schema) -> str | None:
    raw = cast(dict[bytes, bytes] | None, schema.metadata) or {}
    value = raw.get(RELEASE_KEY, b"").decode().strip()
    return value or None


def _valid_hours(value: object, settings: PlantHoursSettings) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value) if 0 < value <= settings.max_hours_per_week else None


def _valid_code(value: object, settings: PlantHoursSettings) -> str | None:
    """The code if it is exactly an ASCII digit string of an accepted length (no trimming)."""
    if not isinstance(value, str) or not (value.isascii() and value.isdigit()):
        return None
    return value if settings.min_digits <= len(value) <= settings.max_digits else None


def _rows(
    codes: list[object],
    hours: list[object],
    settings: PlantHoursSettings,
) -> tuple[dict[str, float], int]:
    """Valid code -> h/week rows, and how many rows were ignored."""
    seen = Counter(code for code in codes if isinstance(code, str))
    kept: dict[str, float] = {}
    for code, value in zip(codes, hours, strict=True):
        clean, h = _valid_code(code, settings), _valid_hours(value, settings)
        if clean is None or h is None or seen[clean] > 1:
            continue
        kept[clean] = h
    return kept, len(codes) - len(kept)


def _problem(schema: pa.Schema, settings: PlantHoursSettings) -> str | None:
    """Why the file cannot be used as a whole, or None."""
    for column in (settings.code_column, settings.hours_column):
        if column not in schema.names:
            return f"missing column {column}"
    return None if _release(schema) else "no release in its metadata"


def _read(settings: PlantHoursSettings) -> Baseline:
    path = settings.baseline_path
    schema = pq.read_schema(path)
    problem = _problem(schema, settings)
    if problem:
        return _empty(f"{path.name}: {problem}")
    columns = [settings.code_column, settings.hours_column]
    data = pq.read_table(path, columns=columns).to_pydict()
    kept, ignored = _rows(data[columns[0]], data[columns[1]], settings)
    note = (f"{path.name}: ignored {ignored} unusable rows",) if ignored else ()
    return Baseline(MappingProxyType(kept), _release(schema) or "", note)


def load_baseline(settings: PlantHoursSettings) -> Baseline:
    """Read and validate the baseline file.

    A missing, unreadable or malformed file (no such column, no release in its metadata) gives an
    empty baseline with one warning, so the caller falls back to the default. Rows with a bad
    code or hours, and every row of a duplicated code, are ignored and counted in one warning.
    """
    try:
        return _read(settings)
    except (OSError, pa.ArrowException) as error:
        return _empty(f"{settings.baseline_path.name} cannot be read: {error}")


@lru_cache(maxsize=4)
def get_baseline(settings: PlantHoursSettings) -> Baseline:
    """The baseline for ``settings``, read once per process; problems are logged once."""
    baseline = load_baseline(settings)
    for message in baseline.warnings:
        logger.warning("plant hours baseline: %s", message)
    return baseline


class PlantHours:
    """Resolves a facility's NAICS code to operating hours per year (callable)."""

    def __init__(
        self,
        baseline: Baseline,
        settings: PlantHoursSettings,
        default_hours_per_year: float,
    ) -> None:
        self._baseline = baseline
        self._settings = settings
        self._default = default_hours_per_year

    def __call__(self, naics_code: str | None) -> OperatingHours:
        """Hours per year for ``naics_code`` (h/yr) and their source; never raises."""
        if not self._baseline.hours_per_week:
            return self._fallback("QPC baseline unavailable")
        code = digit_string(naics_code) if naics_code is not None else None
        if code is None or not MIN_CODE_DIGITS <= len(code) <= self._settings.max_digits:
            return self._fallback("no usable NAICS code")
        hit = longest_prefix(
            self._baseline.hours_per_week,
            code,
            min_length=self._settings.min_digits,
        )
        return self._matched(hit) if hit else self._fallback(f"no QPC match for {code}")

    def _matched(self, hit: tuple[str, float]) -> OperatingHours:
        code, per_week = hit
        per_year = per_week * self._settings.days_per_year / DAYS_PER_WEEK
        source = f"Census QPC {self._baseline.release}, NAICS {code}: {per_week:g} plant hours/week"
        return OperatingHours(per_year, source)

    def _fallback(self, reason: str) -> OperatingHours:
        return OperatingHours(self._default, f"default {self._default:g} h/yr ({reason})")
