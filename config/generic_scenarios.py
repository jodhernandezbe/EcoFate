"""Typed loader for the ``[generic_scenarios]`` settings (worker activities by industry sector)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import project_path, read_toml, section

NAME = "generic_scenarios"


@dataclass(frozen=True)
class GenericScenarioSettings:
    """Where the crosswalk of CDR industrial sectors to generic scenarios is.

    Attributes:
        crosswalk_path: The bundled CSV (sector, life cycle stage, scenario, activities).
    """

    crosswalk_path: Path


def load_generic_scenario_settings(path: Path | None = None) -> GenericScenarioSettings:
    """Load and validate the generic scenario settings.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), NAME)
    return GenericScenarioSettings(crosswalk_path=project_path(table, "crosswalk_path", NAME))


@lru_cache(maxsize=1)
def get_generic_scenario_settings() -> GenericScenarioSettings:
    """Return the cached generic scenario settings from the default file."""
    return load_generic_scenario_settings()
