"""Typed loader for the ``[ecetoc_tra]`` settings (ECETOC TRA tier-1 worker inhalation bands)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import project_path, read_toml, require_number, section

NAME = "ecetoc_tra"


@dataclass(frozen=True)
class EcetocTraSettings:
    """Where the table is and how vapor pressure is banded.

    Attributes:
        table_path: Absolute path of the bundled table (CSV).
        very_low_below_pa: Vapor pressure below which the band is very low, Pa.
        low_up_to_pa: Vapor pressure up to which (inclusive) the band is low, Pa.
        moderate_up_to_pa: Vapor pressure up to which (inclusive) the band is moderate, Pa;
            above it the band is high.
    """

    table_path: Path
    very_low_below_pa: float
    low_up_to_pa: float
    moderate_up_to_pa: float


def load_ecetoc_tra_settings(path: Path | None = None) -> EcetocTraSettings:
    """Load and validate the ECETOC TRA settings.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid, or the limits are not strictly increasing.
    """
    table = section(read_toml(path), NAME)
    limits = tuple(
        require_number(table, key, minimum=1e-9, name=NAME)
        for key in ("very_low_below_pa", "low_up_to_pa", "moderate_up_to_pa")
    )
    if not limits[0] < limits[1] < limits[2]:
        raise ValueError(f"{NAME} band limits must be strictly increasing")
    return EcetocTraSettings(project_path(table, "table_path", NAME), *limits)


@lru_cache(maxsize=1)
def get_ecetoc_tra_settings() -> EcetocTraSettings:
    """Return the cached ECETOC TRA settings from the default file."""
    return load_ecetoc_tra_settings()
