"""Tests for tools.emissions.helpers.inventory.reduce."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from config.loader import EmissionsSettings, TriSettings, get_unit_settings, load_tri_settings
from tools.emissions.helpers.inventory.conditions import Conditions, ConditionsFor
from tools.emissions.helpers.inventory.rate import HoursFor, OperatingHours
from tools.emissions.helpers.inventory.reduce import LatestReports, Location, parse_report
from tools.schemas import EmissionRecord

FIXTURE = Path(__file__).with_name("tri_rows.json")
EMISSIONS = EmissionsSettings(operating_hours_per_year=8760.0)
ALIASES = get_unit_settings().aliases
G_PER_LB = 453.59237


def _row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "epa_registry_id": "110000000001",
        "frs_id": None,
        "reporting_year": "2020",
        "doc_ctrl_num": "1320000000001",
        "environmental_medium": "AIR STACK",
        "total_release": 1000,
        "unit_of_measure": "Pounds",
        "facility_name": "ACME",
        "street_address": "1 MAIN ST",
        "city_name": "TOWN",
        "county_name": "COUNTY",
        "state_abbr": "TX",
        "zip_code": "75001",
        "pref_latitude": 30.0,
        "pref_longitude": 97.0,
    }
    return base | over


def _run(
    rows: list[dict[str, object]],
    settings: TriSettings | None = None,
) -> tuple[list[EmissionRecord], LatestReports]:
    reducer = LatestReports(settings or load_tri_settings(), first_year=0)
    reducer.add_rows(rows)
    return reducer.records(EMISSIONS, ALIASES), reducer


def _only(rows: list[dict[str, object]], settings: TriSettings | None = None) -> EmissionRecord:
    records, _ = _run(rows, settings)
    assert len(records) == 1
    return records[0]


def test_fixture_of_real_rows() -> None:
    rows = json.loads(FIXTURE.read_text())
    records, reducer = _run(rows)
    by_name = {r["facility_name"]: r for r in records}
    assert set(by_name) == {"PORT HAMILTON REFINING & TRANSPORTATION LLLP", "DURO TEXTILES LLC"}
    port = by_name["PORT HAMILTON REFINING & TRANSPORTATION LLLP"]
    assert (port["reporting_year"], port["total_release"], port["unit"]) == (2009, 31070, "Pounds")
    assert port["emission_rate"] == pytest.approx(31070 * G_PER_LB / (8760 * 3600))
    assert (port["latitude"], port["longitude"]) == (17.7, -64.735556)
    assert port["frs_id"] == "110000307864"
    duro = by_name["DURO TEXTILES LLC"]
    assert duro["total_release"] == 909 + 2683
    assert (duro["state"], duro["zip_code"], duro["city"]) == ("MA", "02724", "FALL RIVER")
    assert reducer.stats.no_quantity == 1  # 1988 report with no release
    assert reducer.stats.no_location == 1  # report with no coordinates
    assert reducer.stats.combined == 1


def test_latest_year_wins_in_any_order() -> None:
    rows = [
        _row(reporting_year=y, total_release=q) for y, q in (("1990", 5), ("2022", 7), ("2005", 9))
    ]
    for ordered in (rows, rows[::-1]):
        record = _only(ordered)
        assert (record["reporting_year"], record["total_release"]) == (2022, 7)


def test_latest_year_without_quantity_is_omitted_not_replaced_by_older() -> None:
    rows = [
        _row(reporting_year="2010", total_release=50),
        _row(reporting_year="2021", total_release=None),
    ]
    records, reducer = _run(rows)
    assert records == []
    assert reducer.stats.no_quantity == 1


def test_same_year_reports_are_added() -> None:
    rows = [_row(total_release=909), _row(total_release=2683)]
    records, reducer = _run(rows)
    assert records[0]["total_release"] == 3592
    assert reducer.stats.combined == 1
    assert "added together" in " ".join(reducer.stats.warnings())


def test_same_year_with_one_unusable_report_keeps_the_usable_one() -> None:
    rows = [_row(total_release=None), _row(total_release=40)]
    for ordered in (rows, rows[::-1]):
        assert _only(ordered)["total_release"] == 40


def test_same_year_with_other_unit_is_not_mixed_in() -> None:
    rows = [_row(total_release=10), _row(total_release=99, unit_of_measure="Grams")]
    records, reducer = _run(rows)
    assert records[0]["total_release"] == 10
    assert reducer.stats.mixed_units == 1


def test_each_medium_has_its_own_latest_year() -> None:
    settings = replace(load_tri_settings(), media=("AIR STACK", "AIR FUG"))
    rows = [
        _row(reporting_year="2020", total_release=1),
        _row(reporting_year="2015", total_release=2, environmental_medium="AIR FUG"),
    ]
    records, _ = _run(rows, settings)
    assert {(r["environmental_medium"], r["reporting_year"]) for r in records} == {
        ("AIR STACK", 2020),
        ("AIR FUG", 2015),
    }


def test_other_media_are_dropped() -> None:
    rows = [_row(environmental_medium="LAND TREA"), _row(environmental_medium="OTH DISP")]
    records, reducer = _run(rows)
    assert records == []
    assert reducer.stats.skipped_rows == 2


def test_facility_id_prefers_registry_then_frs_then_skips() -> None:
    assert _only([_row(epa_registry_id="R1", frs_id="F1")])["frs_id"] == "R1"
    assert _only([_row(epa_registry_id=None, frs_id="F1")])["frs_id"] == "F1"
    assert _only([_row(epa_registry_id=" ", frs_id="F1")])["frs_id"] == "F1"
    records, reducer = _run([_row(epa_registry_id=None, frs_id=None)])
    assert records == []
    assert reducer.stats.skipped_rows == 1


def test_facilities_are_kept_apart() -> None:
    rows = [_row(epa_registry_id="A", total_release=1), _row(epa_registry_id="B", total_release=2)]
    records, _ = _run(rows)
    assert {r["frs_id"]: r["total_release"] for r in records} == {"A": 1, "B": 2}


@pytest.mark.parametrize(
    "bad",
    [None, -1, -0.5, math.nan, math.inf, -math.inf, True, False, "12", "", [1], {"a": 1}],
)
def test_bad_quantity_is_omitted(bad: object) -> None:
    records, reducer = _run([_row(total_release=bad)])
    assert records == []
    assert reducer.stats.no_quantity == 1


def test_zero_quantity_is_a_valid_zero_rate() -> None:
    record = _only([_row(total_release=0)])
    assert (record["total_release"], record["emission_rate"]) == (0, 0.0)


@pytest.mark.parametrize("bad", [None, "", "  ", 5])
def test_missing_unit_is_omitted(bad: object) -> None:
    records, reducer = _run([_row(unit_of_measure=bad)])
    assert records == []
    assert reducer.stats.no_quantity == 1


@pytest.mark.parametrize("unit", ["furlongs", "m^3"])
def test_unconvertible_unit_is_omitted(unit: str) -> None:
    records, reducer = _run([_row(unit_of_measure=unit)])
    assert records == []
    assert reducer.stats.bad_unit == 1


@pytest.mark.parametrize("year", [None, "", "abc", "20x0", "-5", True, 2020.5, [], "２０２０"])
def test_bad_year_row_is_skipped(year: object) -> None:
    records, reducer = _run([_row(reporting_year=year)])
    assert records == []
    assert reducer.stats.skipped_rows == 1


def test_year_may_be_an_integer() -> None:
    assert _only([_row(reporting_year=2019)])["reporting_year"] == 2019


def test_western_longitude_is_negative() -> None:
    record = _only([_row(state_abbr="TX", pref_longitude=97.5)])
    assert (record["latitude"], record["longitude"]) == (30.0, -97.5)
    assert _only([_row(pref_longitude=-97.5)])["longitude"] == -97.5


@pytest.mark.parametrize("state", ["GU", "gu", "MP"])
def test_east_longitude_states_stay_positive(state: str) -> None:
    record = _only([_row(state_abbr=state, pref_latitude=13.4, pref_longitude=144.7)])
    assert record["longitude"] == 144.7


def test_hemisphere_unknown_without_state() -> None:
    records, reducer = _run([_row(state_abbr=None)])
    assert records == []
    assert reducer.stats.no_location == 1


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (None, 97.0),
        (30.0, None),
        (91.0, 97.0),
        (-91.0, 97.0),
        (30.0, 181.0),
        (math.nan, 97.0),
        (True, 97.0),
        ("30", 97.0),
    ],
)
def test_bad_coordinates_are_omitted(lat: object, lon: object) -> None:
    records, reducer = _run([_row(pref_latitude=lat, pref_longitude=lon)])
    assert records == []
    assert reducer.stats.no_location == 1


def test_coordinates_come_from_the_latest_row_that_has_them() -> None:
    rows = [
        _row(reporting_year="2010", pref_latitude=31.0, pref_longitude=98.0),
        _row(reporting_year="2015", pref_latitude=32.0, pref_longitude=99.0),
        _row(reporting_year="2022", pref_latitude=None, pref_longitude=None, total_release=3),
    ]
    for ordered in (rows, rows[::-1]):
        record = _only(ordered)
        assert (record["reporting_year"], record["total_release"]) == (2022, 3)
        assert (record["latitude"], record["longitude"]) == (32.0, -99.0)


def test_descriptive_fields_and_blank_values() -> None:
    record = _only([_row(city_name="  ", county_name=None)])
    assert (record["facility_name"], record["address"], record["state"]) == (
        "ACME",
        "1 MAIN ST",
        "TX",
    )
    assert (record["city"], record["county"]) == (None, None)


def test_record_carries_hours_and_rate() -> None:
    record = _only([_row(total_release=8760)])
    assert record["operating_hours_per_year"] == 8760.0
    assert record["emission_rate"] == pytest.approx(G_PER_LB / 3600)
    assert record["total_release"] == 8760
    assert record["unit"] == "Pounds"


def test_rate_uses_the_configured_hours() -> None:
    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_row(total_release=8760)])
    record = reducer.records(EmissionsSettings(4380.0), ALIASES)[0]
    assert record["operating_hours_per_year"] == 4380.0
    assert record["emission_rate"] == pytest.approx(2 * G_PER_LB / 3600)


def test_column_names_come_from_settings() -> None:
    base = load_tri_settings()
    settings = replace(
        base,
        facility_id_fields=("fid",),
        fields={**base.fields, "quantity": "qty", "year": "yr"},
    )
    row = {**_row(), "fid": "Z9", "qty": 4, "yr": 1999}
    record = _only([row], settings)
    assert (record["frs_id"], record["total_release"], record["reporting_year"]) == ("Z9", 4, 1999)


def test_parse_report_keeps_unusable_parts_as_none() -> None:
    report = parse_report(_row(total_release=None, pref_latitude=None), load_tri_settings())
    assert report is not None
    assert (report.quantity, report.location) == (None, None)
    assert report.year == 2020


def test_no_rows_no_records_no_warnings() -> None:
    records, reducer = _run([])
    assert records == []
    assert reducer.stats.warnings() == []


def test_warnings_describe_each_count() -> None:
    _, reducer = _run([_row(total_release=None), _row(environmental_medium="OTH DISP")])
    text = " ".join(reducer.stats.warnings())
    assert "1 rows skipped" in text
    assert "1 facilities omitted: no usable release quantity" in text


def _window(
    rows: list[dict[str, object]],
    first_year: int,
) -> tuple[list[EmissionRecord], LatestReports]:
    reducer = LatestReports(load_tri_settings(), first_year=first_year)
    reducer.add_rows(rows)
    return reducer.records(EMISSIONS, ALIASES), reducer


def test_a_facility_whose_latest_report_is_outside_the_window_is_absent() -> None:
    old = _row(epa_registry_id="110000000001", reporting_year="2010")
    new = _row(epa_registry_id="110000000002", reporting_year="2022")
    records, reducer = _window([old, new], first_year=2017)
    assert [r["frs_id"] for r in records] == ["110000000002"]
    assert reducer.stats.outside_window == 1
    assert any("before the window of recent years" in w for w in reducer.stats.warnings())


def test_the_first_year_of_the_window_is_included() -> None:
    records, reducer = _window(
        [_row(reporting_year="2017"), _row(reporting_year="2016")],
        first_year=2017,
    )
    assert [r["reporting_year"] for r in records] == [2017]
    assert reducer.stats.outside_window == 1


def test_old_rows_do_not_hide_a_recent_one_and_never_win() -> None:
    rows = [_row(reporting_year=str(y), total_release=y) for y in (1999, 2010, 2020)]
    (record,) = _window(rows, first_year=2015)[0]
    assert record["reporting_year"] == 2020 and record["total_release"] == 2020.0 * 1.0


def test_a_window_that_excludes_everything_gives_no_records() -> None:
    records, reducer = _window([_row(reporting_year="2001")], first_year=2017)
    assert records == [] and reducer.stats.outside_window == 1


def test_the_control_number_of_the_reported_year_is_carried() -> None:
    rows = [
        _row(reporting_year="2019", doc_ctrl_num="1319000000001"),
        _row(reporting_year="2021", doc_ctrl_num="1321000000007"),
    ]
    assert _only(rows)["doc_ctrl_num"] == "1321000000007"


def test_same_year_forms_report_the_highest_control_number() -> None:
    rows = [
        _row(reporting_year="2021", doc_ctrl_num="1321000000002"),
        _row(reporting_year="2021", doc_ctrl_num="1321000000009"),
        _row(reporting_year="2021", doc_ctrl_num="1321000000005"),
    ]
    assert _only(rows)["doc_ctrl_num"] == "1321000000009"


def test_a_form_without_a_quantity_does_not_lend_its_control_number() -> None:
    rows = [
        _row(reporting_year="2021", total_release=None, doc_ctrl_num="1321000000099"),
        _row(reporting_year="2021", doc_ctrl_num="1321000000001"),
    ]
    assert _only(rows)["doc_ctrl_num"] == "1321000000001"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_missing_control_number_is_none(value: object) -> None:
    assert _only([_row(doc_ctrl_num=value)])["doc_ctrl_num"] is None


def test_a_missing_control_number_does_not_hide_a_present_one_in_the_same_year() -> None:
    rows = [_row(doc_ctrl_num=None), _row(doc_ctrl_num="1320000000003")]
    assert _only(rows)["doc_ctrl_num"] == "1320000000003"


def _no_coordinates(**over: object) -> dict[str, object]:
    return _row(pref_latitude=None, pref_longitude=None, **over)


def test_a_facility_without_coordinates_is_located_from_frs() -> None:
    asked: list[list[str]] = []

    def locate(frs_ids: Sequence[str]) -> Mapping[str, Location]:
        asked.append(list(frs_ids))
        return {frs_id: Location(12.5, -70.5) for frs_id in frs_ids}

    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_no_coordinates()])
    (record,) = reducer.records(EMISSIONS, ALIASES, locate)
    assert asked == [["110000000001"]]
    assert (record["latitude"], record["longitude"]) == (12.5, -70.5)
    assert reducer.stats.from_frs == 1 and reducer.stats.no_location == 0
    assert any("located from their FRS record" in w for w in reducer.stats.warnings())


def test_every_facility_without_coordinates_is_located_in_one_call() -> None:
    asked: list[list[str]] = []

    def locate(frs_ids: Sequence[str]) -> Mapping[str, Location]:
        asked.append(list(frs_ids))
        return {frs_id: Location(1.0, -1.0) for frs_id in frs_ids}

    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows(
        [
            _no_coordinates(epa_registry_id="110000000001"),
            _no_coordinates(epa_registry_id="110000000002"),
            _row(epa_registry_id="110000000003"),  # TRI has its coordinates
        ],
    )
    assert len(reducer.records(EMISSIONS, ALIASES, locate)) == 3
    assert asked == [["110000000001", "110000000002"]]


def test_tri_coordinates_are_preferred_and_frs_is_not_asked() -> None:
    def locate(frs_ids: Sequence[str]) -> Mapping[str, Location]:
        raise AssertionError("FRS must not be asked when TRI has coordinates")

    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_row()])
    assert len(reducer.records(EMISSIONS, ALIASES, locate)) == 1


def test_frs_is_not_asked_for_a_facility_without_a_quantity() -> None:
    def locate(frs_ids: Sequence[str]) -> Mapping[str, Location]:
        raise AssertionError("no quantity, so no coordinates are needed")

    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_no_coordinates(total_release=None)])
    assert reducer.records(EMISSIONS, ALIASES, locate) == []


def test_a_facility_frs_cannot_locate_is_still_omitted() -> None:
    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_no_coordinates()])
    assert reducer.records(EMISSIONS, ALIASES, lambda _: {}) == []
    assert reducer.stats.no_location == 1 and reducer.stats.from_frs == 0


# --- the primary NAICS code joined into every row ----------------------------------------------


def _naics(code: str | None, primary: object = "1", **over: object) -> dict[str, object]:
    return _row(naics_code=code, primary_ind=primary, **over)


def test_the_record_carries_the_primary_naics_code() -> None:
    assert _only([_naics("311224")])["naics_code"] == "311224"


def test_the_record_leaves_the_title_for_the_tool_to_fill() -> None:
    assert _only([_naics("311224")])["naics_title"] is None


def test_a_submission_repeated_for_its_secondary_codes_is_counted_once() -> None:
    rows = [_naics("311224", "1"), _naics("424510", "0"), _naics("325199", "0")]
    records, reducer = _run(rows)
    (record,) = records
    assert record["total_release"] == 1000  # not 3000
    assert record["naics_code"] == "311224"
    assert reducer.stats.secondary_naics == 2
    assert any("secondary NAICS" in w for w in reducer.stats.warnings())


def test_a_secondary_row_arriving_first_does_not_win() -> None:
    (record,) = _run([_naics("424510", 0), _naics("311224", 1)])[0]
    assert record["naics_code"] == "311224"
    assert record["total_release"] == 1000


def test_a_row_without_a_naics_join_is_kept_without_a_code() -> None:
    (record,) = _run([_row()])[0]
    assert record["naics_code"] is None


@pytest.mark.parametrize("bad", ["", "abc", "1", "1234567", "31-12", 311224.5, True])
def test_an_implausible_naics_code_is_left_out(bad: object) -> None:
    assert _only([_naics(bad)])["naics_code"] is None  # type: ignore[arg-type]


def test_a_numeric_code_is_accepted_as_text() -> None:
    assert _only([_naics(311224)])["naics_code"] == "311224"  # type: ignore[arg-type]


def test_the_naics_of_the_latest_year_wins() -> None:
    rows = [_naics("111111", reporting_year="2019"), _naics("222222", reporting_year="2020")]
    assert _only(rows)["naics_code"] == "222222"


def test_same_year_reports_keep_the_naics_of_the_highest_control_number() -> None:
    rows = [
        _naics("111111", doc_ctrl_num="1320000000002"),
        _naics("222222", doc_ctrl_num="1320000000009"),
        _naics("333333", doc_ctrl_num="1320000000005"),
    ]
    record = _only(rows)
    assert (record["doc_ctrl_num"], record["naics_code"]) == ("1320000000009", "222222")
    assert record["total_release"] == 3000  # three separate forms are still added


def test_a_missing_code_on_the_kept_submission_is_filled_from_another_same_year_form() -> None:
    rows = [
        _naics(None, doc_ctrl_num="1320000000009"),
        _naics("222222", doc_ctrl_num="1320000000002"),
    ]
    assert _only(rows)["naics_code"] == "222222"


def _hours_by_code(table: Mapping[str | None, float]) -> HoursFor:
    def resolve(code: str | None) -> OperatingHours:
        return OperatingHours(table.get(code, 8760.0), f"test source for {code}")

    return resolve


def test_record_without_a_resolver_says_the_default_was_used() -> None:
    record = _only([_row()])
    assert record["operating_hours_source"] == "default 8760 h/yr (configured)"


def test_each_facility_gets_the_hours_of_its_own_naics_code() -> None:
    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows(
        [
            _row(epa_registry_id="110000000001", total_release=8760, naics_code="325211"),
            _row(epa_registry_id="110000000002", total_release=8760, naics_code="324110"),
            _row(epa_registry_id="110000000003", total_release=8760),
        ],
    )
    resolver = _hours_by_code({"325211": 4380.0})
    by_id = {r["frs_id"]: r for r in reducer.records(EMISSIONS, ALIASES, hours_for=resolver)}
    half, full, none = (by_id[f"11000000000{i}"] for i in (1, 2, 3))
    assert half["operating_hours_per_year"] == 4380.0
    assert half["operating_hours_source"] == "test source for 325211"
    assert half["emission_rate"] == pytest.approx(2 * G_PER_LB / 3600)
    assert full["operating_hours_per_year"] == 8760.0
    assert full["emission_rate"] == pytest.approx(G_PER_LB / 3600)
    assert none["operating_hours_source"] == "test source for None"


def test_resolver_is_asked_once_per_facility() -> None:
    asked: list[str | None] = []

    def resolve(code: str | None) -> OperatingHours:
        asked.append(code)
        return OperatingHours(8760.0, "x")

    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_row(naics_code="3252"), _row(epa_registry_id="110000000002")])
    reducer.records(EMISSIONS, ALIASES, hours_for=resolve)
    assert len(asked) == 2


FLAGS = (("produce", "3.1a"), ("reactant", "3.2a"), ("formulation_component", "3.2b"))


def _asked(log: list[tuple[frozenset[str], bool]]) -> ConditionsFor:
    def conditions_for(activities: frozenset[str], seen: bool) -> Conditions:
        log.append((activities, seen))
        return Conditions([], sorted(activities), None)

    return conditions_for


def _activities(
    *rows: dict[str, object],
) -> tuple[list[tuple[frozenset[str], bool]], list[EmissionRecord]]:
    log: list[tuple[frozenset[str], bool]] = []
    reducer = LatestReports(load_tri_settings(), first_year=0, flags=FLAGS)
    reducer.add_rows(list(rows))
    return log, reducer.records(EMISSIONS, ALIASES, conditions_for=_asked(log))


@pytest.mark.parametrize("value", [1, "1", 1.0])
def test_a_flag_set_to_one_is_an_activity(value: object) -> None:
    log, _ = _activities(_row(reactant=value, produce=0))
    assert log == [(frozenset({"3.2a"}), True)]


@pytest.mark.parametrize("value", [0, "0", None, "yes", True, 2, "", "true", []])
def test_other_flag_values_set_nothing(value: object) -> None:
    log, _ = _activities(_row(reactant=value, produce=value))
    assert log == [(frozenset(), True)]


def test_same_year_reports_add_their_activities() -> None:
    log, records = _activities(
        _row(doc_ctrl_num="1", reactant="1"),
        _row(doc_ctrl_num="2", formulation_component="1"),
    )
    assert log == [(frozenset({"3.2a", "3.2b"}), True)] and len(records) == 1


def test_repeated_rows_do_not_repeat_an_activity() -> None:
    log, _ = _activities(_row(reactant="1"), _row(reactant="1"), _row(reactant="1"))
    assert log == [(frozenset({"3.2a"}), True)]


def test_a_later_year_replaces_the_activities() -> None:
    log, _ = _activities(
        _row(reporting_year="2019", produce="1"),
        _row(reporting_year="2020", reactant="1"),
    )
    assert log == [(frozenset({"3.2a"}), True)]


def test_an_earlier_year_adds_nothing() -> None:
    log, _ = _activities(
        _row(reporting_year="2020", reactant="1"),
        _row(reporting_year="2019", produce="1"),
    )
    assert log == [(frozenset({"3.2a"}), True)]


def test_a_report_without_a_quantity_does_not_contribute_activities() -> None:
    log, _ = _activities(
        _row(doc_ctrl_num="1", total_release=None, produce="1"),
        _row(doc_ctrl_num="2", reactant="1"),
    )
    assert log == [(frozenset({"3.2a"}), True)]


def test_rows_without_activity_columns_are_unknown_and_counted() -> None:
    reducer = LatestReports(load_tri_settings(), first_year=0, flags=FLAGS)
    reducer.add_rows([_row(), _row(doc_ctrl_num="2")])
    log: list[tuple[frozenset[str], bool]] = []
    reducer.records(EMISSIONS, ALIASES, conditions_for=_asked(log))
    assert log == [(frozenset(), False)]
    assert any("without TRI activity data" in w for w in reducer.stats.warnings())


def test_no_flags_configured_reads_no_activities_and_counts_nothing() -> None:
    reducer = LatestReports(load_tri_settings(), first_year=0)
    reducer.add_rows([_row(reactant="1")])
    assert reducer.stats.no_activity == 0


def test_the_record_carries_what_the_mapper_returned() -> None:
    _, records = _activities(_row(reactant="1"))
    assert records[0]["lifecycle_stages"] == ["3.2a"]
    assert records[0]["conditions_note"] is None


def test_without_a_mapper_the_record_says_so() -> None:
    record = _only([_row(reactant="1")])
    assert record["conditions_of_use"] == [] and record["lifecycle_stages"] == []
    assert record["conditions_note"] == "conditions of use were not requested"


def test_activities_do_not_change_facilities_or_releases() -> None:
    rows = [_row(doc_ctrl_num="1", total_release=100), _row(doc_ctrl_num="2", total_release=50)]
    plain = _run(rows)[0]
    with_flags = _activities(*[r | {"reactant": "1"} for r in rows])[1]
    assert [(r["frs_id"], r["total_release"]) for r in with_flags] == [
        (r["frs_id"], r["total_release"]) for r in plain
    ]
