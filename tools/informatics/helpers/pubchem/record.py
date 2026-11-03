"""Reading a PubChem PUG View record: finding sections by heading and their statements.

A record is untrusted JSON: ``{"Record": {"Section": [{"TOCHeading": ..., "Section": [...],
"Information": [{"Value": {"StringWithMarkup": [{"String": ...}], "Unit": ...}}]}]}}``. Every
accessor ignores what has an unexpected type and never raises.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from commons.cas import format_cas

PugViewRecord = dict[str, object]


@dataclass(frozen=True)
class Statement:
    """One string of a record's information entries.

    Attributes:
        text: The string as PubChem gives it.
        unit: The entry's separate ``Unit`` field, or None when it has none.
    """

    text: str
    unit: str | None


def _dicts(value: object) -> list[dict[str, object]]:
    """The dict items of ``value`` if it is a list; else empty."""
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def _top_sections(record: object) -> list[dict[str, object]]:
    body = cast(dict[str, object], record).get("Record") if isinstance(record, dict) else None
    return _dicts(cast(dict[str, object], body).get("Section")) if isinstance(body, dict) else []


def has_record(payload: object) -> bool:
    """Whether ``payload`` is a JSON object with a ``Record`` object."""
    return isinstance(payload, dict) and isinstance(
        cast(dict[str, object], payload).get("Record"),
        dict,
    )


def _descend(
    sections: list[dict[str, object]],
    path: Sequence[str],
    found: list[dict[str, object]],
) -> None:
    for section in sections:
        children = _dicts(section.get("Section"))
        if section.get("TOCHeading") == path[0]:
            if len(path) == 1:
                found.append(section)
            else:
                _chain(children, path[1:], found)
        _descend(children, path, found)


def _chain(
    sections: list[dict[str, object]],
    path: Sequence[str],
    found: list[dict[str, object]],
) -> None:
    for section in sections:
        if section.get("TOCHeading") != path[0]:
            continue
        if len(path) == 1:
            found.append(section)
        else:
            _chain(_dicts(section.get("Section")), path[1:], found)


def find_sections(record: object, path: Sequence[str]) -> list[dict[str, object]]:
    """Return the sections reached by ``path``, a chain of ``TOCHeading`` values.

    The first heading is looked for at any depth; each further heading must be a direct child
    of the one before. Sections are returned in record order, without repeats.
    """
    if not path:
        return []
    found: list[dict[str, object]] = []
    _descend(_top_sections(record), path, found)
    unique: list[dict[str, object]] = []
    for section in found:
        if not any(section is seen for seen in unique):
            unique.append(section)
    return unique


def _unit(value: dict[str, object]) -> str | None:
    unit = value.get("Unit")
    return unit.strip() if isinstance(unit, str) and unit.strip() else None


def _entry_statements(entry: dict[str, object]) -> list[Statement]:
    value = entry.get("Value")
    if not isinstance(value, dict):
        return []
    body = cast(dict[str, object], value)
    unit = _unit(body)
    strings = _dicts(body.get("StringWithMarkup"))
    return [
        Statement(text.strip(), unit)
        for item in strings
        if isinstance(text := item.get("String"), str) and text.strip()
    ]


def statements(sections: Sequence[dict[str, object]]) -> list[Statement]:
    """Return every string of the sections' information entries, in record order."""
    found: list[Statement] = []
    for section in sections:
        for entry in _dicts(section.get("Information")):
            found.extend(_entry_statements(entry))
    return found


def named_statements(sections: Sequence[dict[str, object]]) -> list[tuple[str | None, Statement]]:
    """Return every string of the sections' entries with the entry's ``Name`` (None if none)."""
    found: list[tuple[str | None, Statement]] = []
    for section in sections:
        for entry in _dicts(section.get("Information")):
            name = entry.get("Name")
            label = name.strip() if isinstance(name, str) and name.strip() else None
            found.extend((label, item) for item in _entry_statements(entry))
    return found


def confirms_cas(record: object, cas: str, heading: Sequence[str]) -> bool:
    """Whether the record lists ``cas`` among its own CAS registry numbers.

    Args:
        record: The PUG View record.
        cas: Hyphenated CAS number that was searched for.
        heading: Headings leading to the record's CAS numbers.
    """
    listed = statements(find_sections(record, heading))
    return any(format_cas(item.text) == cas for item in listed)
