"""Shared validators for reading ``config/settings.toml`` sections.

Each function raises ``ValueError`` naming the offending key, so configuration errors
surface at load time (setup errors raise; they are never coerced).
"""

from __future__ import annotations

import math
import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

DEFAULT_SETTINGS_PATH = Path(__file__).parent / "settings.toml"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# Names a settings profile (e.g. "production"): ``settings.<profile>.toml`` beside the shipped
# file is laid over it. Unset locally; the production compose file sets it.
PROFILE_ENV_VAR = "ECOFATE_SETTINGS_PROFILE"
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def _load_toml(settings_path: Path) -> dict[str, object]:
    if not settings_path.is_file():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")
    with settings_path.open("rb") as handle:
        return tomllib.load(handle)


def profile_path(environ: Mapping[str, str]) -> Path | None:
    """The profile file ``environ`` selects, or None when no profile is set.

    Raises:
        ValueError: If the profile name is not a plain lowercase name.
        FileNotFoundError: If no settings file exists for the profile.
    """
    name = environ.get(PROFILE_ENV_VAR, "").strip()
    if not name:
        return None
    if not _PROFILE_NAME.match(name):
        raise ValueError(f"{PROFILE_ENV_VAR} must be a lowercase profile name")
    path = DEFAULT_SETTINGS_PATH.with_name(f"settings.{name}.toml")
    if not path.is_file():
        raise FileNotFoundError(f"Settings profile not found: {path.name}")
    return path


def overlay_settings(
    base: dict[str, object],
    overlay: dict[str, object],
    where: str = "",
) -> dict[str, object]:
    """``base`` with ``overlay``'s values laid over it (tables merged key by key).

    Raises:
        ValueError: If the overlay names a key the base lacks, or replaces a table with a value
            (or a value with a table); the message names the key.
    """
    merged = dict(base)
    for key, value in overlay.items():
        name = f"{where}{key}"
        if key not in base:
            raise ValueError(f"settings profile sets {name}, which is not a setting")
        if isinstance(base[key], dict) != isinstance(value, dict):
            raise ValueError(f"settings profile changes the kind of {name}")
        merged[key] = (
            overlay_settings(as_table(base[key], name), as_table(value, name), f"{name}.")
            if isinstance(base[key], dict)
            else value
        )
    return merged


def read_toml(path: Path | None, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Parse the settings file; ``path`` None means the shipped file plus the selected profile.

    An explicit ``path`` (tests, tools) is read alone; no profile is applied to it.
    """
    if path is not None:
        return _load_toml(path)
    data = _load_toml(DEFAULT_SETTINGS_PATH)
    overlay = profile_path(os.environ if environ is None else environ)
    return data if overlay is None else overlay_settings(data, _load_toml(overlay))


def as_table(raw: object, name: str) -> dict[str, object]:
    """Return ``raw`` as a str-keyed dict; raises if it is not a TOML table."""
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a table")
    return {str(k): v for k, v in cast(dict[object, object], raw).items()}


def section(data: dict[str, object], name: str) -> dict[str, object]:
    """Return the top-level table ``name``; raises if it is missing."""
    if not isinstance(data.get(name), dict):
        raise ValueError(f"{name} section is missing")
    return as_table(data[name], name)


def subtable(table: dict[str, object], key: str, name: str) -> dict[str, object]:
    """Return the nested table ``name.key``; raises if it is missing."""
    return as_table(table.get(key), f"{name}.{key}")


def require_str(section: dict[str, object], key: str, name: str) -> str:
    """Return a non-empty string value."""
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}.{key} must be a non-empty string")
    return value


def require_number(section: dict[str, object], key: str, *, minimum: float, name: str) -> float:
    """Return a finite number >= ``minimum`` (> 0 when ``minimum`` is positive); never a bool."""
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name}.{key} must be a number")
    if value < minimum or (minimum > 0 and value == 0):
        raise ValueError(f"{name}.{key} must be >= {minimum}")
    return float(value)


def require_int(section: dict[str, object], key: str, *, minimum: int, name: str) -> int:
    """Return an integer >= ``minimum``; never a bool."""
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}.{key} must be an integer")
    if value < minimum:
        raise ValueError(f"{name}.{key} must be >= {minimum}")
    return value


def require_bool(section: dict[str, object], key: str, name: str) -> bool:
    """Return a TOML boolean; never a number or string that looks like one."""
    value = section.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{name}.{key} must be true or false")
    return value


def require_fraction(section: dict[str, object], key: str, name: str) -> float:
    """Return a finite number in [0, 1]; never a bool."""
    value = require_number(section, key, minimum=0, name=name)
    if value > 1:
        raise ValueError(f"{name}.{key} must be between 0 and 1")
    return value


def names(section: dict[str, object], key: str, name: str, *, allow_empty: bool) -> tuple[str, ...]:
    """Return a list of non-empty strings, stripped."""
    value = section.get(key)
    items = cast(list[object], value) if isinstance(value, list) else None
    if items is None or (not items and not allow_empty):
        raise ValueError(f"{name}.{key} must be a non-empty list of strings")
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError(f"{name}.{key} must be a list of non-empty strings")
    return tuple(cast(str, item).strip() for item in items)


def project_path(section: dict[str, object], key: str, name: str) -> Path:
    """Return a path value; a relative path is resolved against the project root."""
    path = Path(require_str(section, key, name).strip())
    return path if path.is_absolute() else PROJECT_ROOT / path


def require_pair(
    section: dict[str, object],
    key: str,
    *,
    minimum: float,
    name: str,
) -> tuple[float, float]:
    """Return a two-number list as a tuple, each finite and >= ``minimum`` (never a bool)."""
    value = section.get(key)
    items = cast(list[object], value) if isinstance(value, list) else None
    if items is None or len(items) != 2:
        raise ValueError(f"{name}.{key} must be a list of two numbers")
    first = require_number({key: items[0]}, key, minimum=minimum, name=name)
    second = require_number({key: items[1]}, key, minimum=minimum, name=name)
    return first, second
