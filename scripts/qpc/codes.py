"""Published NAICS code expressions -> the four-digit codes a row covers.

The QPC table writes codes as numbers or text, with footnote markers (``51312 3/``), comma
lists that replace trailing digits of the first code (``3111,7,8``) and hyphen ranges over the
last digit (``3321,2,4-6``, ``332992-4``). A four-digit code is attributed to a row only when
the row covers it entirely; anything finer or coarser is skipped with a reason.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from scripts.qpc.errors import RowSkipped

FOOTNOTES = re.compile(r"(\s+\d+/)+\s*$")
TOKEN = re.compile(r"(\d+)(?:-(\d+))?")
FOUR_DIGITS = 4
THREE_DIGITS = 3
PART_OF_FOUR = (5, 6)
MAX_CODE_LENGTH = 6
MAX_SPAN = 100


def clean_cell(cell: str | int | float) -> str:
    """The code cell as text with footnote markers and all whitespace removed."""
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    return "".join(FOOTNOTES.sub("", str(cell)).split())


def _span(first: str, last: str, width: int) -> list[str]:
    start, end = int(first[-width:]), int(last)
    if end < start or end - start >= MAX_SPAN or len(last) > width:
        raise ValueError(f"bad range {first}-{last}")
    return [f"{first[:-width]}{n:0{width}d}" for n in range(start, end + 1)]


def _expand(token: str, base: str) -> list[str]:
    found = TOKEN.fullmatch(token)
    if found is None:
        raise ValueError(f"cannot read {token!r} as a code")
    start, end = found.groups()
    if base == "":
        return _span(start, end, len(end)) if end else [start]
    width = len(start)
    full = f"{base[:-width]}{start}" if width <= len(base) else ""
    if not full:
        raise ValueError(f"{token!r} is longer than the code {base!r}")
    return _span(full, end, width) if end else [full]


def parse_codes(cell: str | int | float) -> tuple[str, ...]:
    """Every NAICS code the cell names, in order.

    Raises:
        ValueError: If the cell is not a code expression.
    """
    tokens = clean_cell(cell).split(",")
    first = _expand(tokens[0], "")
    codes = list(first)
    base = TOKEN.fullmatch(tokens[0])
    if base is None:
        raise ValueError(f"cannot read {tokens[0]!r} as a code")
    for token in tokens[1:]:
        codes += _expand(token, base.group(1))
    if len(set(map(len, codes))) != 1 or len(codes[0]) > MAX_CODE_LENGTH:
        raise ValueError(f"{clean_cell(cell)!r} mixes code lengths or is too long")
    return tuple(dict.fromkeys(codes))


def four_digit_codes(
    codes: tuple[str, ...],
    children: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """The four-digit codes the row covers entirely.

    Args:
        codes: The row's codes, all of one length (from ``parse_codes``).
        children: Three-digit code -> its four-digit codes in the configured NAICS edition.

    Raises:
        RowSkipped: If the row covers part of a four-digit code, is an aggregate, or a
            three-digit code has no listed children.
    """
    length = len(codes[0])
    if length == FOUR_DIGITS:
        return codes
    if length == THREE_DIGITS:
        return _children(codes, children)
    if length in PART_OF_FOUR:
        raise RowSkipped("covers only part of a four-digit code")
    raise RowSkipped("aggregate shorter than three digits")


def _children(codes: tuple[str, ...], children: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    missing = [code for code in codes if not children.get(code)]
    if missing:
        raise RowSkipped(f"no four-digit codes listed under {missing[0]} for this NAICS edition")
    return tuple(dict.fromkeys(child for code in codes for child in children[code]))
