"""Tests for heading traversal and statement reading of a PUG View record."""

from __future__ import annotations

import pytest

from tests.tools.informatics.helpers.pubchem.records import info, record, section
from tools.informatics.helpers.pubchem.record import (
    confirms_cas,
    find_sections,
    has_record,
    statements,
)

CAS_PATH = ("Names and Identifiers", "Other Identifiers", "CAS")


def test_has_record() -> None:
    assert has_record({"Record": {}})
    wrong: list[object] = [{}, [], None, "x", {"Record": []}, {"Record": None}]
    assert not any(has_record(x) for x in wrong)


def test_section_found_by_heading_chain() -> None:
    found = find_sections(record(cas=["106-97-8"]), CAS_PATH)
    assert len(found) == 1 and found[0]["TOCHeading"] == "CAS"


def test_first_heading_is_found_at_any_depth() -> None:
    inner = section("Other Identifiers", section("CAS", entries=[info("106-97-8")]))
    deep = {"Record": {"Section": [section("Wrapper", section("Names and Identifiers", inner))]}}
    assert len(find_sections(deep, CAS_PATH)) == 1


def test_later_headings_must_be_direct_children() -> None:
    skipped = section("Names and Identifiers", section("CAS", entries=[info("106-97-8")]))
    assert find_sections({"Record": {"Section": [skipped]}}, CAS_PATH) == []


def test_repeated_sections_are_all_returned_in_order() -> None:
    body = {
        "Record": {
            "Section": [section("A", entries=[info("1")]), section("A", entries=[info("2")])],
        },
    }
    assert [s.text for s in statements(find_sections(body, ("A",)))] == ["1", "2"]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "x",
        {},
        {"Record": None},
        {"Record": {"Section": "x"}},
        {"Record": {"Section": [1, None]}},
    ],
)
def test_unexpected_shapes_find_nothing_and_do_not_raise(bad: object) -> None:
    assert find_sections(bad, CAS_PATH) == []
    assert find_sections(bad, ()) == []


def test_non_string_headings_are_ignored() -> None:
    body = {"Record": {"Section": [section(5), section(None), section(["CAS"])]}}
    assert find_sections(body, ("CAS",)) == []


def test_statements_read_strings_and_units() -> None:
    sec = section("S", entries=[info("58", "g/mol"), info(" text ")])
    assert [(s.text, s.unit) for s in statements([sec])] == [("58", "g/mol"), ("text", None)]


def test_statements_ignore_entries_of_the_wrong_type() -> None:
    sec: dict[str, object] = {
        "TOCHeading": "S",
        "Information": [
            1,
            {"Value": None},
            {"Value": {"StringWithMarkup": "x"}},
            {"Value": {"StringWithMarkup": [{"String": 5}, {"String": "  "}, {"String": True}]}},
            {"Value": {"StringWithMarkup": [{"String": "ok"}], "Unit": 7}},
        ],
    }
    assert [(s.text, s.unit) for s in statements([sec])] == [("ok", None)]


def test_cas_is_confirmed_by_the_record_itself() -> None:
    assert confirms_cas(record(cas=["71-43-2", "106-97-8"]), "106-97-8", CAS_PATH)


def test_other_cas_numbers_do_not_confirm() -> None:
    assert not confirms_cas(record(cas=["71-43-2"]), "106-97-8", CAS_PATH)


def test_text_that_only_contains_the_cas_number_does_not_confirm() -> None:
    assert not confirms_cas(record(cas=["see 106-97-8 or other"]), "106-97-8", CAS_PATH)


def test_no_cas_section_does_not_confirm() -> None:
    assert not confirms_cas(record(), "106-97-8", CAS_PATH)
    assert not confirms_cas({}, "106-97-8", CAS_PATH)
