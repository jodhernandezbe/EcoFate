"""The TRI category member index, read once from the committed member list.

TRI reports some chemicals only as members of a category (N420, lead compounds). The index
answers "which categories list this CAS number" by exact match; names are never used as a
key because the source file contains typos.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from commons.cas import format_cas
from config.tri_categories import TriCategoriesSettings, get_tri_categories_settings
from tools.schemas import CategoryRef

_BAD_CAS = "invalid CAS number"
_NO_CODE = "empty category code"
_BAD_CODE = "category code that is neither a group code nor a valid CAS number"


@dataclass(frozen=True)
class Category:
    """One TRI category a chemical belongs to.

    Attributes:
        code: Group code (N420) or, for a single-substance entry, its hyphenated CAS number.
        name: Category name as TRI gives it.
        chemical_type: "Organic" or "Inorganic" as the member list gives it.
    """

    code: str
    name: str
    chemical_type: str


@dataclass(frozen=True)
class Member:
    """A chemical listed under one or more categories.

    Attributes:
        cas: Hyphenated CAS number.
        name: Name from the list (display only; may contain typos).
        organic: Whether any row types the member organic.
        categories: Every category that lists it, in file order.
    """

    cas: str
    name: str
    organic: bool
    categories: tuple[Category, ...]


def category_refs(categories: tuple[Category, ...]) -> list[CategoryRef]:
    """The categories as the tools return them: code and name, in order."""
    return [{"code": c.code, "name": c.name} for c in categories]


@dataclass(frozen=True)
class CategoryLookup:
    """The answer to one membership question: categories found (possibly none) and warnings."""

    categories: tuple[Category, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CategoryIndex:
    """All members, by CAS number, plus how many rows were dropped and why.

    Attributes:
        members: Members by hyphenated CAS number (read-only).
        code_names: Every category code present, with its name.
        dropped: Rows dropped, by reason.
    """

    members: Mapping[str, Member]
    code_names: Mapping[str, str]
    dropped: Mapping[str, int]

    @property
    def codes(self) -> frozenset[str]:
        """Every category code present."""
        return frozenset(self.code_names)

    def lookup(self, raw_cas: str) -> CategoryLookup:
        """Return the categories that list ``raw_cas`` (an invalid CAS gives none and a warning)."""
        cas = format_cas(raw_cas)
        if cas is None:
            return CategoryLookup((), (f"CAS number {raw_cas!r} is not valid",))
        member = self.members.get(cas)
        return CategoryLookup(member.categories if member else (), ())

    def has_code(self, code: str) -> bool:
        """Whether ``code`` is a category code on the list."""
        return code in self.code_names

    def name_of(self, code: str) -> str | None:
        """The name of category ``code``, or None if it is not on the list."""
        return self.code_names.get(code)


def _category_code(raw: str) -> str | None:
    """A group code as written, a digits-only code as a hyphenated CAS, else None."""
    code = raw.strip()
    return format_cas(code) if code.isdigit() else code


def _row_parts(
    row: Mapping[str, str],
    settings: TriCategoriesSettings,
) -> tuple[str, Category, str] | str:
    """The (CAS, category, member name) of a row, or the reason it cannot be trusted."""
    cas = format_cas(row[settings.cas_column])
    if cas is None:
        return _BAD_CAS
    raw_code = row[settings.code_column]
    if not raw_code.strip():
        return _NO_CODE
    code = _category_code(raw_code)
    if code is None:
        return _BAD_CODE
    category = Category(
        code,
        row[settings.category_name_column].strip(),
        row[settings.type_column].strip(),
    )
    return cas, category, row[settings.member_name_column].strip()


def _missing_columns(fields: Sequence[str] | None, settings: TriCategoriesSettings) -> list[str]:
    wanted = (
        settings.cas_column,
        settings.code_column,
        settings.category_name_column,
        settings.member_name_column,
        settings.type_column,
    )
    return [column for column in wanted if column not in (fields or [])]


def _read_rows(settings: TriCategoriesSettings) -> list[dict[str, str]]:
    with settings.path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = _missing_columns(reader.fieldnames, settings)
        if missing:
            raise ValueError(f"{settings.path} lacks column(s) {missing}")
        return list(reader)


def _add(grouped: dict[str, list[tuple[Category, str]]], parts: tuple[str, Category, str]) -> None:
    cas, category, name = parts
    if all(category != seen for seen, _ in grouped[cas]):
        grouped[cas].append((category, name))


def _member(cas: str, entries: list[tuple[Category, str]], organic_value: str) -> Member:
    categories = tuple(category for category, _ in entries)
    organic = any(category.chemical_type == organic_value for category in categories)
    return Member(cas, entries[0][1], organic, categories)


def load_index(settings: TriCategoriesSettings) -> CategoryIndex:
    """Read and validate the member list.

    Raises:
        FileNotFoundError: If the member list does not exist.
        ValueError: If a configured column is missing from it.
    """
    grouped: dict[str, list[tuple[Category, str]]] = defaultdict(list)
    dropped: dict[str, int] = defaultdict(int)
    for row in _read_rows(settings):
        parts = _row_parts(row, settings)
        if isinstance(parts, str):
            dropped[parts] += 1
        else:
            _add(grouped, parts)
    members = {
        cas: _member(cas, entries, settings.organic_value) for cas, entries in grouped.items()
    }
    names = {c.code: c.name for member in members.values() for c in member.categories}
    return CategoryIndex(
        MappingProxyType(members),
        MappingProxyType(names),
        MappingProxyType(dict(dropped)),
    )


@lru_cache(maxsize=1)
def get_category_index() -> CategoryIndex:
    """Return the cached index built from the shipped member list."""
    return load_index(get_tri_categories_settings())
