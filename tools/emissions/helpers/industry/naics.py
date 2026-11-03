"""The primary NAICS code of one TRI submission and the title of that code."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from urllib.parse import quote

from config.industry import IndustrySettings
from tools.digits import digit_string
from tools.emissions.helpers.efservice import EfserviceClient, EfserviceError, Row
from tools.emissions.helpers.naics_titles import naics_titles
from tools.schemas import FacilityIndustry

SOURCE = "TRI submission NAICS"
_BIG = 10**9


def _none(warnings: Sequence[str]) -> FacilityIndustry:
    return FacilityIndustry(
        naics_code=None,
        naics_title=None,
        code_origin=None,
        source=None,
        warnings=list(warnings),
    )


def _code(row: Row, settings: IndustrySettings) -> str | None:
    """Return the row's NAICS code if the row is a primary one, else None."""
    if str(row.get(settings.primary_field)).strip() != settings.primary_value:
        return None
    value = row.get(settings.code_field)
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return digit_string(value)


def _sequence(row: Row, settings: IndustrySettings) -> int:
    value = row.get(settings.sequence_field)
    return value if isinstance(value, int) and not isinstance(value, bool) else _BIG


@dataclass(frozen=True)
class _Primary:
    """The chosen primary row of a submission and what else was seen."""

    code: str | None
    row: Row | None
    codes: frozenset[str]
    placeholders: frozenset[str]


def _coded(
    rows: Sequence[Row],
    settings: IndustrySettings,
) -> tuple[list[tuple[int, str, Row]], set[str]]:
    """Rows with a real code, sorted by sequence then code, and the placeholder codes seen."""
    real: list[tuple[int, str, Row]] = []
    placeholders: set[str] = set()
    for row in rows:
        code = _code(row, settings)
        if code is None:
            continue
        if code in settings.placeholder_codes:
            placeholders.add(code)
        else:
            real.append((_sequence(row, settings), code, row))
    real.sort(key=lambda item: item[:2])
    return real, placeholders


def _primary(rows: Sequence[Row], settings: IndustrySettings) -> _Primary:
    """Choose the primary row with the lowest sequence number; note other codes and placeholders."""
    real, placeholders = _coded(rows, settings)
    first = real[0] if real else None
    codes = frozenset(code for _, code, _ in real)
    return _Primary(
        first[1] if first else None,
        first[2] if first else None,
        codes,
        frozenset(placeholders),
    )


def _origin(row: Row, settings: IndustrySettings) -> str | None:
    value = str(row.get(settings.origin_field) or "").strip().lower()
    if value == settings.reported_value.lower():
        return "reported"
    return "assigned" if value == settings.assigned_value.lower() else None


def _title(code: str, client: EfserviceClient, settings: IndustrySettings) -> str | None:
    """The title of ``code``: from the local code lists, else TRI's reference table, else None."""
    local = naics_titles(settings).get(code)
    if local is not None:
        return local
    path = settings.title_path.format(naics_code=quote(code, safe=""))
    try:
        rows = client.get_rows(path)
    except EfserviceError:
        return None
    for row in rows:
        title = row.get(settings.title_field)
        same = str(row.get(settings.code_field)).strip() == code
        if same and isinstance(title, str) and title.strip():
            return title.strip()
    return None


def _notes(code: str, title: str | None, origin: str | None, codes: Collection[str]) -> list[str]:
    notes: list[str] = []
    if origin == "assigned":
        notes.append(
            f"EPA assigned NAICS code {code} (the facility did not report it), "
            "so it may be generic",
        )
    if len(codes) > 1:
        notes.append(
            f"the submission lists {len(codes)} primary NAICS codes; "
            f"{code}, the first, is returned",
        )
    if title is None:
        notes.append(
            f"no title was found for NAICS code {code}; the title is needed before the SCC "
            "process search can be used",
        )
    return notes


def _nothing(doc: str, placeholders: Collection[str]) -> str:
    if not placeholders:
        return f"TRI reports no primary NAICS code for submission {doc}"
    shown = ", ".join(sorted(placeholders))
    return (
        f"the only primary NAICS code of submission {doc} is {shown}, "
        "a placeholder and not an industry"
    )


def _fetch_rows(doc: str, client: EfserviceClient, settings: IndustrySettings) -> list[Row] | None:
    path = settings.submission_naics_path.format(doc_ctrl_num=quote(doc, safe=""))
    try:
        return client.get_rows(path)
    except EfserviceError:
        return None


def submission_industry(
    doc_ctrl_num: str | int,
    client: EfserviceClient,
    settings: IndustrySettings,
) -> FacilityIndustry:
    """Look up the primary NAICS code of a TRI submission and the title of that code.

    Args:
        doc_ctrl_num: Control number of the submission (the `doc_ctrl_num` of an emission
            record), as text of digits or an integer.
        client: Envirofacts client (injected).
        settings: Query paths, field names, primary indicator, origin labels, placeholders.

    Returns:
        The code, its title, whether the facility reported it or EPA assigned it, a source
        label and warnings; or nulls plus a warning when the control number is invalid, TRI
        lists no usable primary code, the only code is a placeholder or the request failed.
        Never raises on data or network problems.
    """
    doc = digit_string(doc_ctrl_num)
    if doc is None:
        return _none([f"control number {doc_ctrl_num!r} is invalid: it must be digits only"])
    rows = _fetch_rows(doc, client, settings)
    if rows is None:
        return _none(
            [f"the industry of submission {doc} could not be looked up (TRI is unreachable)"],
        )
    pick = _primary(rows, settings)
    if pick.code is None or pick.row is None:
        return _none([_nothing(doc, pick.placeholders)])
    return _result(pick.code, pick, client, settings)


def _result(
    code: str,
    pick: _Primary,
    client: EfserviceClient,
    settings: IndustrySettings,
) -> FacilityIndustry:
    title = _title(code, client, settings)
    origin = _origin(pick.row, settings) if pick.row is not None else None
    return FacilityIndustry(
        naics_code=code,
        naics_title=title,
        code_origin=origin,
        source=SOURCE,
        warnings=_notes(code, title, origin, pick.codes),
    )
