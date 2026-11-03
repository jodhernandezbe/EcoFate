"""Tests for scripts.qpc.codes."""

from __future__ import annotations

import pytest

from scripts.qpc.codes import clean_cell, four_digit_codes, parse_codes
from scripts.qpc.errors import RowSkipped

CHILDREN = {"313": ("3131", "3132"), "314": ("3141",)}


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("3111,7,8", ("3111", "3117", "3118")),
        ("3321,2,4-6", ("3321", "3322", "3324", "3325", "3326")),
        ("332992-4", ("332992", "332993", "332994")),
        ("334412,6-9", ("334412", "334416", "334417", "334418", "334419")),
        ("51312 3/", ("51312",)),
        ("51311,3 2/", ("51311", "51313")),
        ("31-33 1/", ("31", "32", "33")),
        (3112, ("3112",)),
        (3112.0, ("3112",)),
        ("  3121 ", ("3121",)),
        (313, ("313",)),
    ],
)
def test_parse_codes(cell: str | int | float, expected: tuple[str, ...]) -> None:
    assert parse_codes(cell) == expected


@pytest.mark.parametrize(
    "cell",
    ["abc", "3321,", "3111,77777", "33-2", "3111,x", "", "1/", "c  The rate"],
)
def test_garbage_is_rejected(cell: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_codes(cell)


def test_clean_cell_strips_footnotes_and_spaces() -> None:
    assert clean_cell("51312 3/") == "51312"
    assert clean_cell("3321, 2, 4-6") == "3321,2,4-6"


def test_four_digit_codes_pass_through() -> None:
    assert four_digit_codes(("3111", "3117"), CHILDREN) == ("3111", "3117")


def test_three_digit_codes_expand_to_children() -> None:
    assert four_digit_codes(("313", "314"), CHILDREN) == ("3131", "3132", "3141")


def test_three_digit_code_without_children_is_skipped() -> None:
    with pytest.raises(RowSkipped, match="no four-digit codes listed under 315"):
        four_digit_codes(("315",), CHILDREN)


@pytest.mark.parametrize("codes", [("32411",), ("325194", "325199")])
def test_part_of_a_four_digit_code_is_skipped(codes: tuple[str, ...]) -> None:
    with pytest.raises(RowSkipped, match="only part"):
        four_digit_codes(codes, CHILDREN)


def test_aggregate_is_skipped() -> None:
    with pytest.raises(RowSkipped, match="aggregate"):
        four_digit_codes(("31", "32", "33"), CHILDREN)
