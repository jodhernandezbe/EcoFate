"""Typed loader for the ``[byok]`` settings: per-user key encryption in the web program."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import read_toml, require_int, require_str, section

_NAME = "byok"


@dataclass(frozen=True)
class ByokSettings:
    """Key-encryption settings. The key-encryption keys are never stored, only their variables.

    Attributes:
        kek_env_var: Environment variable holding the current key-encryption key.
        previous_kek_env_var: Environment variable holding the previous one during a rotation.
        rotation_batch_size: Stored keys re-sealed per database round trip by ``rotate-keys``.
    """

    kek_env_var: str
    previous_kek_env_var: str
    rotation_batch_size: int


def load_byok_settings(path: Path | None = None) -> ByokSettings:
    """Load and validate the ``[byok]`` settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid, or the two variables are the same; the
            message names the key.
    """
    table = section(read_toml(path), _NAME)
    current = require_str(table, "kek_env_var", _NAME).strip()
    previous = require_str(table, "previous_kek_env_var", _NAME).strip()
    if not current or not previous:
        raise ValueError(f"{_NAME}.kek_env_var and previous_kek_env_var must not be blank")
    if current == previous:
        raise ValueError(f"{_NAME}.previous_kek_env_var must differ from kek_env_var")
    return ByokSettings(
        kek_env_var=current,
        previous_kek_env_var=previous,
        rotation_batch_size=require_int(table, "rotation_batch_size", minimum=1, name=_NAME),
    )


@lru_cache(maxsize=1)
def get_byok_settings() -> ByokSettings:
    """Return the cached ``[byok]`` settings from the default file."""
    return load_byok_settings()
