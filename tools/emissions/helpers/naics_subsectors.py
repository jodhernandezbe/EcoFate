"""Three-digit NAICS subsector of a facility and its title, from the local Census table.

The dashboard groups facilities by subsector (e.g. 325 Chemical Manufacturing), which the
six-digit code of a record names by its first three digits. The titles come from
``[industry].subsectors_path`` (built by ``scripts.build_naics_subsectors``), never generated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from config.industry import IndustrySettings
from tools.digits import digit_string
from tools.emissions.helpers.naics_titles import read_titles
from tools.schemas import EmissionRecord

SUBSECTOR_DIGITS = 3


def subsector_titles(settings: IndustrySettings) -> Mapping[str, str]:
    """The subsector code -> title table named by the settings (read once, read-only).

    Raises:
        FileNotFoundError: If the table does not exist.
        ValueError: If it lacks the configured columns.
    """
    return read_titles(
        settings.subsectors_path,
        settings.subsectors_code_column,
        settings.subsectors_title_column,
    )


def subsector_of(naics_code: str | None) -> str | None:
    """The first three digits of a NAICS code, or None when it has no code or fewer digits."""
    code = digit_string(naics_code) if naics_code is not None else None
    return code[:SUBSECTOR_DIGITS] if code is not None and len(code) >= SUBSECTOR_DIGITS else None


def with_subsectors(
    records: Sequence[EmissionRecord],
    titles: Mapping[str, str],
) -> list[EmissionRecord]:
    """Copies of ``records`` with ``naics_subsector`` and its title filled in.

    A record without a usable code has neither; a subsector the table lacks keeps a null title.
    """
    out: list[EmissionRecord] = []
    for record in records:
        subsector = subsector_of(record["naics_code"])
        title = titles.get(subsector) if subsector is not None else None
        out.append({**record, "naics_subsector": subsector, "naics_subsector_title": title})
    return out
