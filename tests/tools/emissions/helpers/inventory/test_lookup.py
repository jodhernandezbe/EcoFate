"""Tests for tools.emissions.helpers.inventory.lookup."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from config.conditions_of_use import get_conditions_settings
from config.efservice import load_efservice_settings
from config.loader import EmissionsSettings, TriSettings, get_unit_settings, load_tri_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.inventory import conditions as module
from tools.emissions.helpers.inventory.conditions import ConditionsMapper, load_crosswalk
from tools.emissions.helpers.inventory.lookup import TriReadError, lookup_emissions
from tools.emissions.helpers.inventory.rate import OperatingHours
from tools.emissions.helpers.inventory.tri import TriFetcher
from tools.schemas import EmissionRecord

ROWS = json.loads(Path(__file__).with_name("tri_rows.json").read_text())
SETTINGS = replace(load_tri_settings(), page_size=4, max_pages=3, recent_years=1000)
YEAR = 2012  # with the wide window above, every fixture row (1988 to 2009) is recent
EMISSIONS = EmissionsSettings(8760.0)
CAS = "50-00-0"


def _fetcher(transport: httpx.MockTransport, settings: TriSettings = SETTINGS) -> TriFetcher:
    client = EfserviceClient(
        load_efservice_settings(),
        httpx.Client(transport=transport),
        lambda _seconds: None,
    )
    return TriFetcher(settings, client, YEAR)


def _serve(pages: Sequence[Sequence[Mapping[str, object]]]) -> httpx.MockTransport:
    queue = list(pages)
    # The fugitive medium is queried last; once the pages are served it has nothing to report.
    return httpx.MockTransport(
        lambda request: httpx.Response(200, json=queue.pop(0) if queue else []),
    )


def _lookup(
    fetcher: TriFetcher,
    settings: TriSettings = SETTINGS,
    year: int = YEAR,
) -> list[EmissionRecord]:
    found = lookup_emissions(CAS, settings, EMISSIONS, get_unit_settings().aliases, fetcher, year)
    return found.stack


def test_rows_across_pages_are_reduced() -> None:
    fetcher = _fetcher(_serve([ROWS[:4], ROWS[4:]]))
    records = _lookup(fetcher)
    assert {r["frs_id"] for r in records} == {"110000307864", "110021074834"}


def test_nothing_reported_gives_empty_list() -> None:
    assert _lookup(_fetcher(_serve([[]]))) == []


def test_each_configured_medium_is_queried() -> None:
    settings = replace(SETTINGS, media=("AIR STACK", "WATER"))
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=[])

    _lookup(_fetcher(httpx.MockTransport(handler), settings), settings)
    assert [("AIR%20STACK" in u, "WATER" in u, "AIR%20FUG" in u) for u in urls] == [
        (True, False, False),
        (False, True, False),
        (False, False, True),
    ]


def test_failure_raises_instead_of_returning_empty(caplog: pytest.LogCaptureFixture) -> None:
    """A failed read is never an empty result: that would read as no releases."""
    answers = [httpx.Response(200, json=ROWS[:4])] + [httpx.Response(500)] * 3
    transport = httpx.MockTransport(lambda request: answers.pop(0))
    with caplog.at_level(logging.WARNING), pytest.raises(TriReadError, match="HTTP 500"):
        _lookup(_fetcher(transport))
    assert "failed" in caplog.text


def test_page_cap_is_warned(caplog: pytest.LogCaptureFixture) -> None:
    full = [{**ROWS[0], "epa_registry_id": f"F{i}"} for i in range(4)]
    with caplog.at_level(logging.WARNING):
        records = _lookup(_fetcher(_serve([full, full, full])))
    assert len(records) == 4
    assert "page cap" in caplog.text


def test_data_warnings_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        _lookup(_fetcher(_serve([ROWS[:4], ROWS[4:]])))
    assert "no usable release quantity" in caplog.text
    assert "added together" in caplog.text


def test_hours_resolver_reaches_every_record() -> None:
    def resolve(code: str | None) -> OperatingHours:
        return OperatingHours(4380.0, f"from {code}")

    records = lookup_emissions(
        CAS, SETTINGS, EMISSIONS, get_unit_settings().aliases,
        _fetcher(_serve([ROWS[:4], ROWS[4:]])), YEAR, hours_for=resolve,
    ).stack  # fmt: skip
    assert records and {r["operating_hours_per_year"] for r in records} == {4380.0}
    assert all(r["operating_hours_source"].startswith("from ") for r in records)


def test_without_a_resolver_the_default_hours_are_used() -> None:
    records = _lookup(_fetcher(_serve([ROWS[:4], ROWS[4:]])))
    assert {r["operating_hours_per_year"] for r in records} == {8760.0}


def _mapper() -> ConditionsMapper:
    settings = get_conditions_settings()
    return ConditionsMapper(load_crosswalk(settings), settings)


def _with_conditions(rows: list[dict[str, object]]) -> list[EmissionRecord]:
    return lookup_emissions(
        CAS, SETTINGS, EMISSIONS, get_unit_settings().aliases,
        _fetcher(_serve([rows[:4], rows[4:]])), YEAR, conditions=_mapper(),
    ).stack  # fmt: skip


def test_activities_become_conditions_of_use() -> None:
    rows = [r | {"produce": "1", "reactant": "1", "imported": "0"} for r in ROWS]
    records = _with_conditions(rows)
    assert records
    for record in records:
        assert record["lifecycle_stages"] == ["Manufacturing", "Processing"]
        assert [c["tri_section"] for c in record["conditions_of_use"]] == ["3.1a", "3.2a"]
        assert record["conditions_note"] is None


def test_rows_without_activity_columns_have_a_note_not_a_guess() -> None:
    records = _with_conditions(ROWS)
    assert {r["conditions_note"] for r in records} == {module.NO_ACTIVITY_DATA}
    assert all(r["conditions_of_use"] == [] for r in records)


def test_the_flags_come_from_the_mapper_not_the_lookup() -> None:
    assert dict(_mapper().flags)["reactant"] == "3.2a"
    records = _lookup(_fetcher(_serve([ROWS[:4], ROWS[4:]])))
    assert {r["conditions_note"] for r in records} == {"conditions of use were not requested"}
