"""Titles of six-digit NAICS codes from the local Census code lists.

Shared by the emissions inventory (every record carries its industry in words) and the facility
industry tool (which asks Envirofacts only for a code the lists do not have).
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from config.industry import IndustrySettings
from tools.digits import digit_string
from tools.schemas import FacilityRecord


@lru_cache(maxsize=4)
def read_titles(path: Path, code_column: str, title_column: str) -> Mapping[str, str]:
    """Read the table once. A missing file or column is a setup error and raises."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        if code_column not in columns or title_column not in columns:
            raise ValueError(f"{path} must have the columns {code_column!r} and {title_column!r}")
        titles: dict[str, str] = {}
        for row in reader:
            code = digit_string(row.get(code_column) or "")
            title = " ".join((row.get(title_column) or "").split())
            if code is not None and title:
                titles.setdefault(code, title)
    return MappingProxyType(titles)


def naics_titles(settings: IndustrySettings) -> Mapping[str, str]:
    """The code -> title table named by the settings (read once, returned read-only).

    Raises:
        FileNotFoundError: If the table does not exist.
        ValueError: If it lacks the configured columns.
    """
    return read_titles(
        settings.titles_path,
        settings.titles_code_column,
        settings.titles_title_column,
    )


def with_titles[R: FacilityRecord](
    records: Sequence[R],
    titles: Mapping[str, str],
) -> list[R]:
    """Copies of ``records`` with ``naics_title`` filled from ``titles`` where the code is known.

    A record without a code, or with one the table lacks (a shorter code, a vintage not
    listed), keeps a null title.
    """
    out: list[R] = []
    for record in records:
        code = record["naics_code"]
        titled = record.copy()
        titled["naics_title"] = titles.get(code) if code is not None else None
        out.append(titled)
    return out
