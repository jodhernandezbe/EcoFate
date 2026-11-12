"""Tests for tools.emissions.helpers.inventory.listing."""

from __future__ import annotations

from tests.tools.emissions.records import emission_record, worker_only_facility
from tools.emissions.helpers.inventory.listing import rank_and_cap, with_worker_only

RECORDS = [
    emission_record("a", 1.0),
    emission_record("b", 5.0, "LA", "Geismar"),
    emission_record("c", 3.0),
    emission_record("d", 4.0, "LA", "Baton Rouge"),
]


def test_the_largest_come_first_and_the_rest_are_cut() -> None:
    view, every = rank_and_cap(RECORDS, 2)
    assert [f["frs_id"] for f in view["facilities"]] == ["b", "d"]
    assert [f["frs_id"] for f in every] == ["b", "d", "c", "a"]
    assert (view["total_found"], view["matching"], view["shown"]) == (4, 4, 2)


def test_a_partial_list_says_so_and_how_to_see_others() -> None:
    view, _ = rank_and_cap(RECORDS, 2)
    assert view["note"] and "4" in view["note"] and "`state` or `city`" in view["note"]


def test_a_complete_list_has_no_note() -> None:
    view, _ = rank_and_cap(RECORDS, 10)
    assert view["note"] is None and view["shown"] == 4


def test_state_and_city_filters_ignore_case_and_whitespace() -> None:
    view, every = rank_and_cap(RECORDS, 10, state=" la ")
    assert [f["frs_id"] for f in view["facilities"]] == ["b", "d"]
    assert (view["total_found"], view["matching"]) == (4, 2)
    assert [f["frs_id"] for f in rank_and_cap(RECORDS, 10, city="GEISMAR")[1]] == ["b"]
    assert len(every) == 2


def test_both_filters_must_match() -> None:
    assert rank_and_cap(RECORDS, 10, state="LA", city="Houston")[0]["matching"] == 0


def test_a_blank_filter_means_no_filter() -> None:
    assert rank_and_cap(RECORDS, 10, state="  ", city="")[0]["matching"] == 4


def test_nothing_matching_says_so_only_when_a_filter_was_given() -> None:
    assert rank_and_cap(RECORDS, 10, state="ZZ")[0]["note"] == "No facility matches the filters."
    assert rank_and_cap([], 10)[0]["note"] is None


def test_a_facility_without_a_state_never_matches_a_state_filter() -> None:
    view, _ = rank_and_cap([emission_record("x", 1.0, state=None)], 10, state="TX")
    assert view["matching"] == 0


def test_the_input_is_not_changed() -> None:
    copy = list(RECORDS)
    rank_and_cap(RECORDS, 2)
    assert RECORDS == copy


WORKERS = [
    worker_only_facility("w1", 5.0),
    worker_only_facility("w2", 50.0, "LA", "Geismar"),
    worker_only_facility("w3", None),
    worker_only_facility("w4", 20.0, "LA", "Baton Rouge"),
]


def test_worker_only_facilities_are_listed_apart_largest_release_first() -> None:
    view, _ = rank_and_cap(RECORDS, 10)
    both = with_worker_only(view, WORKERS, 10)
    assert [w["frs_id"] for w in both["worker_only"]] == ["w2", "w4", "w1", "w3"]
    assert both["worker_only_left_out"] == 0 and both["note"] is None


def test_the_stack_figures_are_unchanged_by_worker_only_facilities() -> None:
    view, _ = rank_and_cap(RECORDS, 2)
    both = with_worker_only(view, WORKERS, 10)
    for key in ("total_found", "matching", "shown", "facilities", "note"):
        assert both[key] == view[key]  # type: ignore[literal-required]


def test_more_than_the_cap_keeps_the_largest_and_says_how_many_were_left_out() -> None:
    view, _ = rank_and_cap(RECORDS, 10)
    capped = with_worker_only(view, WORKERS, 2)
    assert [w["frs_id"] for w in capped["worker_only"]] == ["w2", "w4"]
    assert capped["worker_only_left_out"] == 2
    assert capped["note"] is not None and "2 more" in capped["note"]


def test_the_cap_note_follows_the_stack_note() -> None:
    view, _ = rank_and_cap(RECORDS, 2)
    note = with_worker_only(view, WORKERS, 1)["note"]
    assert note is not None and note.startswith(str(view["note"]))


def test_worker_only_facilities_follow_the_state_and_city_filters() -> None:
    view, _ = rank_and_cap(RECORDS, 10, state="LA")
    found = with_worker_only(view, WORKERS, 10, state=" la ")
    assert [w["frs_id"] for w in found["worker_only"]] == ["w2", "w4"]
    city = with_worker_only(view, WORKERS, 10, city="geismar")
    assert [w["frs_id"] for w in city["worker_only"]] == ["w2"]


def test_no_worker_only_facility_leaves_the_result_empty() -> None:
    view, _ = rank_and_cap(RECORDS, 10)
    assert view["worker_only"] == [] and view["worker_only_left_out"] == 0
    assert with_worker_only(view, [], 10) == view
