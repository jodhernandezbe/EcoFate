"""Tests for query_emissions_inventory."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import ToolMessage

from config.efservice import get_efservice_settings
from config.plant_hours import get_plant_hours_settings
from tests.tools.emissions.records import emission_record
from tools.emissions import inventory
from tools.emissions.helpers.inventory.plant_hours import get_baseline
from tools.emissions.helpers.inventory.rate import OperatingHours
from tools.emissions.inventory import clear_inventory_cache, query_emissions_inventory
from tools.registry import get_all_tools
from tools.schemas import EmissionRecord, InventoryResult

CURRENT_YEAR = 2011  # the fixture rows are real and run from 1988 to 2009; 2009-2010 count
ROWS = json.loads((Path(__file__).parent / "helpers" / "inventory" / "tri_rows.json").read_text())


@pytest.fixture
def requests_seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "mv_new_geo_best_picks" in str(request.url) or "frs_program_facility" in str(
            request.url,
        ):
            return httpx.Response(200, json=[])  # FRS has no point, and no EIS registration
        if "AIR%20FUG" in str(request.url):
            return httpx.Response(200, json=[])  # no fugitive release; `seen` counts stack queries
        seen.append(request)
        return httpx.Response(200, json=ROWS)

    monkeypatch.setattr(
        inventory,
        "_open_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings = replace(get_efservice_settings(), delay_seconds=0.0, backoff_seconds=0.0)
    monkeypatch.setattr(inventory, "get_efservice_settings", lambda: settings)
    monkeypatch.setattr(inventory, "_current_year", lambda: CURRENT_YEAR)
    monkeypatch.setattr(inventory, "_hours_for", lambda: _default_hours)
    return seen


def _default_hours(_code: str | None) -> OperatingHours:
    """No industry hours: keeps these tests independent of the committed baseline."""
    return OperatingHours(8760.0, "default 8760 h/yr (test)")


def _call(args: dict[str, object]) -> ToolMessage:
    return query_emissions_inventory.invoke(
        {"type": "tool_call", "id": "c1", "name": "query_emissions_inventory", "args": args},
    )


def _view(args: dict[str, object]) -> InventoryResult:
    """What the model is told."""
    return json.loads(str(_call(args).content))


def _all(args: dict[str, object]) -> list[EmissionRecord]:
    """What the program gets beside it: every matching facility."""
    return _call(args).artifact


def test_schema() -> None:
    assert query_emissions_inventory.name == "query_emissions_inventory"
    assert set(query_emissions_inventory.args) == {"cas_number", "state", "city"}
    assert query_emissions_inventory.description
    assert query_emissions_inventory in get_all_tools()


def test_docstring_describes_every_returned_field() -> None:
    text = query_emissions_inventory.description
    for field in (
        "frs_id",
        "emission_rate",
        "total_release",
        "unit",
        "operating_hours_per_year",
        "operating_hours_source",
        "fugitive_release_kg_per_year",
        "fugitive_reporting_year",
        "naics_subsector",
        "naics_subsector_title",
        "conditions_of_use",
        "lifecycle_stages",
        "conditions_note",
        "latitude",
    ):
        assert field in text
    assert "reporting_year" in text


def test_returns_latest_records_with_rates(requests_seen: list[httpx.Request]) -> None:
    records = _all({"cas_number": "50-00-0"})
    assert len(requests_seen) == 1
    url = str(requests_seen[0].url)
    assert "/cas_registry_number/50-00-0/environmental_medium/AIR%20STACK/" in url
    assert "/reporting_year/%3E/2008/rows/0:" in url  # the last two years ending in 2010
    by_id = {r["frs_id"]: r for r in records}
    assert by_id["110000307864"]["reporting_year"] == 2009
    assert by_id["110000307864"]["unit"] == "Pounds"
    assert by_id["110000307864"]["emission_rate"] == pytest.approx(
        31070 * 453.59237 / (8760 * 3600),
    )
    assert by_id["110000307864"]["operating_hours_per_year"] == 8760.0


def test_bare_cas_is_accepted(requests_seen: list[httpx.Request]) -> None:
    _view({"cas_number": " 50000 "})
    assert "/cas_registry_number/50-00-0/" in str(requests_seen[0].url)


@pytest.mark.parametrize("bad", ["", "abc", "50-00-1", "1-2-3", "50-00-0; DROP", "N999", "N4200"])
def test_invalid_cas_makes_no_request(
    requests_seen: list[httpx.Request],
    caplog: pytest.LogCaptureFixture,
    bad: str,
) -> None:
    with caplog.at_level(logging.WARNING):
        assert _view({"cas_number": bad})["facilities"] == []
    assert requests_seen == []
    assert "not a valid CAS" in caplog.text


def test_category_code_is_queried_as_given_and_the_note_says_whole_category(
    requests_seen: list[httpx.Request],
) -> None:
    view = _view({"cas_number": " n420 "})
    assert "/cas_registry_number/N420/environmental_medium/" in str(requests_seen[0].url)
    assert view["total_found"] > 0
    assert view["note"] is not None
    assert "whole TRI category N420 (LEAD COMPOUNDS)" in view["note"]


def test_a_cas_number_has_no_category_note(requests_seen: list[httpx.Request]) -> None:
    assert _view({"cas_number": "1336-36-3"})["note"] is None
    assert "/cas_registry_number/1336-36-3/" in str(requests_seen[0].url)


def test_a_facility_that_stopped_reporting_long_ago_is_not_returned(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In 2026 only 2024 and 2025 count; the fixture's last report is 2009."""
    monkeypatch.setattr(inventory, "_current_year", lambda: 2026)
    assert _all({"cas_number": "50-00-0"}) == []


def test_every_record_carries_its_submission_control_number(
    requests_seen: list[httpx.Request],
) -> None:
    records = _all({"cas_number": "50-00-0"})
    assert records and all("doc_ctrl_num" in record for record in records)
    assert any(record["doc_ctrl_num"] for record in records)


def test_listed_facilities_carry_their_eis_ids(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _view({"cas_number": "50-00-0"})
    listed = view["facilities"]
    assert listed and all(record["eis_ids"] == [] for record in listed)
    assert all("no EIS registration" in (record["eis_note"] or "") for record in listed)


def test_description_explains_the_window_and_the_control_number() -> None:
    text = " ".join(query_emissions_inventory.description.split())
    for phrase in ("last 2 reporting years", "doc_ctrl_num", "fetch_facility_industry"):
        assert phrase in text, phrase


def test_the_model_is_told_the_largest_facilities_and_how_many_there_are(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _list_at_most(monkeypatch, 3)
    view = _view({"cas_number": "50-00-0"})
    every = _all({"cas_number": "50-00-0"})
    assert view["total_found"] == view["matching"] == len(every) > 3
    assert view["shown"] == len(view["facilities"]) == 3
    assert view["note"] and "must not be treated as complete" in view["note"]
    rates = [f["emission_rate"] for f in view["facilities"]]
    assert rates == sorted(rates, reverse=True)
    assert rates == [f["emission_rate"] for f in every[:3]]  # the largest of all of them


def test_the_program_gets_every_facility_even_when_the_model_sees_few(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _list_at_most(monkeypatch, 1)
    every = _all({"cas_number": "50-00-0"})
    assert len(every) == _view({"cas_number": "50-00-0"})["total_found"]
    assert [f["emission_rate"] for f in every] == sorted(
        (f["emission_rate"] for f in every),
        reverse=True,
    )


def test_the_artifact_is_never_part_of_the_text_the_model_reads(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _list_at_most(monkeypatch, 2)
    message = _call({"cas_number": "50-00-0"})
    assert len(json.loads(str(message.content))["facilities"]) == 2
    assert len(message.artifact) > 2


def test_a_state_filter_lists_that_state_and_says_so(requests_seen: list[httpx.Request]) -> None:
    every = _all({"cas_number": "50-00-0"})
    state = next(f["state"] for f in every if f["state"])
    view = _view({"cas_number": "50-00-0", "state": str(state).lower()})
    assert view["total_found"] == len(every)
    assert 0 < view["matching"] <= view["total_found"]
    assert {f["state"] for f in view["facilities"]} == {state}
    assert len(_all({"cas_number": "50-00-0", "state": state})) == view["matching"]


def test_no_match_says_so_and_is_not_an_error(requests_seen: list[httpx.Request]) -> None:
    view = _view({"cas_number": "50-00-0", "state": "ZZ"})
    assert (view["matching"], view["shown"], view["facilities"]) == (0, 0, [])
    assert view["note"] == "No facility matches the filters."


def test_description_tells_the_model_the_list_is_the_largest_and_partial() -> None:
    text = " ".join(query_emissions_inventory.description.split())
    for phrase in (
        "highest `emission_rate` first",
        "total_found",
        "Never present a list as complete",
        "`state`",
    ):
        assert phrase in text


def _list_at_most(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    """List at most ``count`` facilities to the model, from a result of six facilities."""
    settings = replace(inventory.get_tri_settings(), max_listed=count)
    monkeypatch.setattr(inventory, "get_tri_settings", lambda: settings)
    many = [emission_record(f"F{i}", float(i), "TX" if i % 2 else "LA") for i in range(6)]

    def fake_lookup(*args: object, **kwargs: object) -> list[EmissionRecord]:
        return many

    monkeypatch.setattr(inventory, "lookup_emissions", fake_lookup)


def test_the_same_inventory_is_read_once_while_it_is_remembered(
    requests_seen: list[httpx.Request],
) -> None:
    first = _all({"cas_number": "50-00-0"})
    asked = len(requests_seen)
    again = _all({"cas_number": "50-00-0"})
    assert again == first and len(requests_seen) == asked
    clear_inventory_cache()
    _all({"cas_number": "50-00-0"})
    assert len(requests_seen) > asked


def test_eis_ids_are_remembered_but_an_unreachable_frs_is_not() -> None:
    asked: list[list[str]] = []

    def resolve(records: list[EmissionRecord]) -> list[EmissionRecord]:
        asked.append([r["frs_id"] for r in records])
        return [
            {**r, "eis_ids": ["9"] if r["frs_id"] == "A" else [], "eis_note": None} for r in records
        ]

    first = inventory.remembered_eis(resolve, [emission_record("A", 1.0)])
    both = inventory.remembered_eis(resolve, [emission_record("A", 1.0), emission_record("B", 1.0)])
    assert first[0]["eis_ids"] == ["9"] and [r["eis_ids"] for r in both] == [["9"], []]
    assert asked == [["A"], ["B"]]  # A was not asked again

    def down(records: list[EmissionRecord]) -> list[EmissionRecord]:
        asked.append([r["frs_id"] for r in records])
        return [{**r, "eis_ids": [], "eis_note": inventory.UNREACHABLE_NOTE} for r in records]

    inventory.remembered_eis(down, [emission_record("C", 1.0)])
    inventory.remembered_eis(down, [emission_record("C", 1.0)])
    assert asked[-2:] == [["C"], ["C"]]  # a failed lookup is tried again


def test_each_facility_gets_the_hours_of_its_industry(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def by_industry(code: str | None) -> OperatingHours:
        return OperatingHours(4380.0, f"test hours for {code}")

    monkeypatch.setattr(inventory, "_hours_for", lambda: by_industry)
    clear_inventory_cache()
    records = _all({"cas_number": "50-00-0"})
    port = next(r for r in records if r["frs_id"] == "110000307864")
    assert port["operating_hours_per_year"] == 4380.0
    assert port["operating_hours_source"] == f"test hours for {port['naics_code']}"
    assert port["emission_rate"] == pytest.approx(31070 * 453.59237 / (4380 * 3600))


def test_the_real_resolver_uses_the_committed_baseline_and_the_default() -> None:
    baseline = get_baseline(get_plant_hours_settings())
    code, per_week = next(iter(baseline.hours_per_week.items()))
    resolve = inventory._hours_for()  # pyright: ignore[reportPrivateUsage]
    assert resolve(code + "0" * (6 - len(code))).hours_per_year == pytest.approx(per_week * 365 / 7)
    assert resolve("999999").hours_per_year == 8760.0
    assert resolve(None).source.startswith("default 8760 h/yr")


def test_the_release_request_joins_the_activity_table(requests_seen: list[httpx.Request]) -> None:
    _all({"cas_number": "50-00-0"})
    assert "/tri_submission_naics/tri_chem_activity/cas_registry_number/50-00-0/" in str(
        requests_seen[0].url,
    )


def test_the_program_gets_each_facilitys_conditions_of_use(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [r | {"reactant": "1", "ancillary": "1", "produce": 0} for r in ROWS]
    monkeypatch.setattr("tests.tools.emissions.test_inventory.ROWS", rows)
    clear_inventory_cache()
    record = _all({"cas_number": "50-00-0"})[0]
    assert record["lifecycle_stages"] == ["Processing", "Industrial use", "Commercial use"]
    assert [c["tri_section"] for c in record["conditions_of_use"]] == ["3.2a", "3.3c", "3.3c"]
    assert record["conditions_note"] is None


def test_rows_without_activity_data_are_explained(requests_seen: list[httpx.Request]) -> None:
    record = _all({"cas_number": "50-00-0"})[0]
    assert record["conditions_of_use"] == [] and "did not return" in str(record["conditions_note"])


def test_the_program_gets_each_facilitys_subsector(requests_seen: list[httpx.Request]) -> None:
    for record in _all({"cas_number": "50-00-0"}):
        code = record["naics_code"]
        assert record["naics_subsector"] == (code[:3] if code else None)
        if code and len(code) >= 3:
            assert record["naics_subsector_title"]  # in the committed table


def test_unreadable_tri_is_never_reported_as_no_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a failed TRI request (HTTP 500) is a note that says so, not an empty list."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "mv_new_geo_best_picks" in str(request.url) or "frs_program_facility" in str(
            request.url,
        ):
            return httpx.Response(200, json=[])
        return httpx.Response(500)

    monkeypatch.setattr(
        inventory,
        "_open_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings = replace(get_efservice_settings(), delay_seconds=0.0, backoff_seconds=0.0)
    monkeypatch.setattr(inventory, "get_efservice_settings", lambda: settings)
    monkeypatch.setattr(inventory, "_current_year", lambda: CURRENT_YEAR)
    monkeypatch.setattr(inventory, "_hours_for", lambda: _default_hours)
    clear_inventory_cache()
    view = _view({"cas_number": "50-00-0"})
    assert view["facilities"] == [] and view["total_found"] == 0
    note = view["note"] or ""
    assert "TRI could not be read" in note
    assert "not evidence that there are no releases" in note
