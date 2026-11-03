"""The current TRI chemical list (Envirofacts ``tri_chem_info``), reduced to discrete chemicals.

Used by the catalog builder only. A TRI group or placeholder (N420 "Lead compounds",
MIXTURE, TRD SECRT, ...) has no CAS number in its CAS field, so it has no single structure
and is skipped; so are chemicals delisted from TRI, unless configured otherwise.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from commons.cas import format_cas
from config.efservice import EfserviceSettings
from config.read_across import TriListSettings
from tools.http import HttpRequestError, RetryingClient

_MAX_PAGES = 50  # guard against a server that ignores the row range and repeats a full page

GROUP = "group or placeholder (no CAS number)"
DELISTED = "delisted from TRI"
DUPLICATE = "repeated CAS number"

type Row = dict[str, object]


class TriListError(RuntimeError):
    """The TRI list could not be read or no longer has the configured fields."""


@dataclass(frozen=True)
class TriChemical:
    """One discrete TRI chemical: hyphenated CAS number and name."""

    cas: str
    name: str


@dataclass(frozen=True)
class TriList:
    """The kept chemicals, in list order, and how many rows were dropped for each reason."""

    chemicals: tuple[TriChemical, ...]
    dropped: Mapping[str, int]


def _rows(payload: object, settings: TriListSettings) -> list[Row]:
    if not isinstance(payload, list):
        raise TriListError("TRI chemical list: unexpected answer (not a list of rows)")
    rows: list[Row] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise TriListError("TRI chemical list: unexpected answer (a row is not an object)")
        row = {str(k): v for k, v in cast(dict[object, object], item).items()}
        missing = [f for f in _fields(settings) if f not in row]
        if missing:
            raise TriListError(f"TRI chemical list: field {missing[0]!r} is missing")
        rows.append(row)
    return rows


def _fields(settings: TriListSettings) -> tuple[str, ...]:
    return (settings.cas_field, settings.name_field, settings.inactive_field)


def _page(
    start: int,
    client: RetryingClient,
    efservice: EfserviceSettings,
    settings: TriListSettings,
) -> list[Row]:
    url = efservice.url(settings.page_path(start))
    try:
        return _rows(client.get_json(url), settings)
    except HttpRequestError as exc:
        raise TriListError(f"TRI chemical list could not be read: {exc}") from exc


def fetch_rows(
    client: RetryingClient,
    efservice: EfserviceSettings,
    settings: TriListSettings,
) -> list[Row]:
    """Read every row of the TRI list, page by page, while pages come back full.

    Raises:
        TriListError: If a request fails, the answer is malformed, a configured field is
            missing, or the list never ends within the page guard.
    """
    rows: list[Row] = []
    for page in range(_MAX_PAGES):
        batch = _page(page * settings.page_size, client, efservice, settings)
        rows.extend(batch)
        if len(batch) < settings.page_size:
            return rows
    raise TriListError(f"TRI chemical list did not end within {_MAX_PAGES} pages")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _drop_reason(row: Row, settings: TriListSettings, seen: set[str]) -> str | None:
    cas = format_cas(_text(row[settings.cas_field]))
    if cas is None:
        return GROUP
    inactive = row[settings.inactive_field]
    listed = inactive is None or _text(inactive) == settings.active_value
    if not listed and not settings.keep_delisted:
        return DELISTED
    return DUPLICATE if cas in seen else None


def discrete_chemicals(rows: list[Row], settings: TriListSettings) -> TriList:
    """Keep the discrete, listed chemicals of the TRI list, first occurrence of each CAS.

    Args:
        rows: Rows of ``tri_chem_info`` (each has the configured fields).
        settings: Field names, the "still listed" value and whether delisted ones are kept.

    Returns:
        The kept chemicals (named by the CAS number when the name is blank) and the number
        of rows dropped per reason.
    """
    kept: list[TriChemical] = []
    seen: set[str] = set()
    dropped: Counter[str] = Counter()
    for row in rows:
        reason = _drop_reason(row, settings, seen)
        if reason is not None:
            dropped[reason] += 1
            continue
        cas = cast(str, format_cas(_text(row[settings.cas_field])))
        seen.add(cas)
        kept.append(TriChemical(cas, _text(row[settings.name_field]) or cas))
    return TriList(tuple(kept), dict(dropped))
