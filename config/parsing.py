"""Shared validators for reading ``config/settings.toml`` sections.

Each function raises ``ValueError`` naming the offending key, so configuration errors
surface at load time (setup errors raise; they are never coerced).
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import cast

DEFAULT_SETTINGS_PATH = Path(__file__).parent / "settings.toml"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_toml(path: Path | None) -> dict[str, object]:
    """Parse the settings file (``DEFAULT_SETTINGS_PATH`` when ``path`` is None)."""
    settings_path = path or DEFAULT_SETTINGS_PATH
    if not settings_path.is_file():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")
    with settings_path.open("rb") as handle:
        return tomllib.load(handle)


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
