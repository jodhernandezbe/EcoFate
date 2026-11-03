"""Typed loader for the ``[conditions_of_use]`` settings (TSCA conditions of use)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import project_path, read_toml, require_str, section, subtable

NAME = "conditions_of_use"
SECTION_KEY = re.compile(r"3\.[123][a-f]")


@dataclass(frozen=True)
class ConditionsSettings:
    """Where the crosswalk is, which of its rows and columns to read, and which TRI flags count.

    Attributes:
        crosswalk_path: CSV mapping TRI activities to TSCA conditions of use; absolute or
            resolved against the project root.
        level: Value of ``level_column`` whose rows are used (rows with a sub-use code are not).
        level_column, section_column, subuse_column, stage_column, category_column,
            strength_column, activity_column: Names of the crosswalk columns read.
        section_pattern: Regex with group ``section`` that extracts "3.2b" from the section cell.
        flags: (``tri_chem_activity`` column, Form R section) pairs, in section order.
    """

    crosswalk_path: Path
    level: str
    level_column: str
    section_column: str
    subuse_column: str
    stage_column: str
    category_column: str
    strength_column: str
    activity_column: str
    section_pattern: re.Pattern[str]
    flags: tuple[tuple[str, str], ...]


def _text(table: dict[str, object], key: str) -> str:
    return require_str(table, key, NAME).strip()


def _pattern(table: dict[str, object]) -> re.Pattern[str]:
    try:
        compiled = re.compile(_text(table, "section_pattern"))
    except re.error as error:
        raise ValueError(
            f"{NAME}.section_pattern is not a valid regular expression: {error}",
        ) from error
    if "section" not in compiled.groupindex:
        raise ValueError(f"{NAME}.section_pattern must have the named group 'section'")
    return compiled


def _flags(table: dict[str, object]) -> tuple[tuple[str, str], ...]:
    raw = subtable(table, "flags", NAME)
    if not raw:
        raise ValueError(f"{NAME}.flags must list at least one flag")
    pairs = [(column, require_str(raw, column, f"{NAME}.flags").strip()) for column in raw]
    for column, code in pairs:
        if not SECTION_KEY.fullmatch(code):
            raise ValueError(f"{NAME}.flags.{column} must be a Form R section like 3.2b")
    if len({code for _, code in pairs}) != len(pairs):
        raise ValueError(f"{NAME}.flags must not repeat a section")
    return tuple(sorted(pairs, key=lambda pair: pair[1]))


def load_conditions_settings(path: Path | None = None) -> ConditionsSettings:
    """Load and validate the conditions-of-use settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), NAME)
    return ConditionsSettings(
        crosswalk_path=project_path(table, "crosswalk_path", NAME),
        level=_text(table, "level"),
        level_column=_text(table, "level_column"),
        section_column=_text(table, "section_column"),
        subuse_column=_text(table, "subuse_column"),
        stage_column=_text(table, "stage_column"),
        category_column=_text(table, "category_column"),
        strength_column=_text(table, "strength_column"),
        activity_column=_text(table, "activity_column"),
        section_pattern=_pattern(table),
        flags=_flags(table),
    )


@lru_cache(maxsize=1)
def get_conditions_settings() -> ConditionsSettings:
    """Return the cached conditions-of-use settings from the default file."""
    return load_conditions_settings()
