"""Typed loader for the ``[risk_bands]`` settings (boundaries of the screening bands)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from config.parsing import read_toml, require_number, section

NAME = "risk_bands"


@dataclass(frozen=True)
class RiskBands:
    """Boundaries of the high, moderate and low bands, shared by both pathways.

    A value from the lower boundary is "moderate", from the upper boundary "high"; a value on a
    boundary goes to the higher band.

    Attributes:
        hq_lower: Hazard quotient from which the band is moderate, unitless.
        hq_upper: Hazard quotient from which the band is high, unitless.
        cancer_risk_lower: Lifetime cancer risk from which the band is moderate, probability.
        cancer_risk_upper: Lifetime cancer risk from which the band is high, probability.
        oel_ratio_lower: Ratio to the occupational limit from which the band is moderate, unitless.
        oel_ratio_upper: Ratio to the occupational limit from which the band is high, unitless.
    """

    hq_lower: float
    hq_upper: float
    cancer_risk_lower: float
    cancer_risk_upper: float
    oel_ratio_lower: float
    oel_ratio_upper: float

    def boundaries(
        self,
        quantity: Literal["hq", "cancer_risk", "oel_ratio"],
    ) -> tuple[float, float]:
        """The (lower, upper) boundaries of one quantity."""
        return getattr(self, f"{quantity}_lower"), getattr(self, f"{quantity}_upper")


def _pair(table: dict[str, object], quantity: str) -> tuple[float, float]:
    lower = require_number(table, f"{quantity}_lower", minimum=1e-30, name=NAME)
    upper = require_number(table, f"{quantity}_upper", minimum=1e-30, name=NAME)
    if lower >= upper:
        raise ValueError(f"{NAME}.{quantity}_lower must be below {NAME}.{quantity}_upper")
    return lower, upper


def load_risk_bands(path: Path | None = None) -> RiskBands:
    """Load and validate the band boundaries.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid or a lower boundary is not below its upper;
            the message names the key.
    """
    table = section(read_toml(path), NAME)
    hq, risk, ratio = _pair(table, "hq"), _pair(table, "cancer_risk"), _pair(table, "oel_ratio")
    return RiskBands(hq[0], hq[1], risk[0], risk[1], ratio[0], ratio[1])


@lru_cache(maxsize=1)
def get_risk_bands() -> RiskBands:
    """Return the cached band boundaries from the default file."""
    return load_risk_bands()
