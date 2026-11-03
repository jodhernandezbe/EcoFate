"""Tests for tools.emissions.helpers.inventory.eis (a mock FRS service; synthetic IDs)."""

from __future__ import annotations

import re
from urllib.parse import unquote

import httpx
import pytest

from config.efservice import EfserviceSettings
from config.frs_eis import FrsEisSettings
from tests.tools.emissions.records import emission_record
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.inventory.eis import EisResolver, distance_km
from tools.schemas import EmissionRecord

SETTINGS = FrsEisSettings(
    base_url="https://frs.test",
    eis_path="/eis/{frs_ids}",
    registry_field="registry_id",
    eis_id_field="pgm_sys_id",
    sites_path="/sites/{frs_ids}",
    twins_path="/twins/{names}/{state}",
    twin_single_path="/twin/{name}/{state}",
    name_field="primary_name",
    state_field="state_code",
    latitude_field="latitude",
    longitude_field="longitude",
    batch_size=2,
    max_twin_distance_km=0.5,
    twin_list_pattern=re.compile(r"^[A-Za-z0-9 .-]+$"),
    twin_batch_size=2,
    twin_workers=2,
    cache_seconds=0.0,
)
EF = EfserviceSettings("https://frs.test", 0.0, 5.0, 0, 0.0)
A, B, C, TWIN, FAR = "110000000001", "110000000002", "110000000003", "110000000009", "110000000008"
Row = dict[str, object]


def _reg(frs_id: str, eis: object) -> Row:
    return {"registry_id": frs_id, "pgm_sys_acrnm": "EIS", "pgm_sys_id": eis}


def _site(
    frs_id: str,
    name: str = "PLANT ONE",
    state: str = "TX",
    lat: float = 30.0,
    lon: object = -95.0,
) -> Row:
    return {
        "registry_id": frs_id,
        "primary_name": name,
        "state_code": state,
        "latitude": lat,
        "longitude": lon,
    }


class Service:
    """A mock FRS: EIS registrations by FRS ID, site rows by FRS ID and by (name, state)."""

    def __init__(
        self,
        registrations: dict[str, list[object]] | None = None,
        sites: dict[str, Row] | None = None,
        twins: dict[tuple[str, str], list[Row]] | None = None,
        failing: str | None = None,
        rejects: str | None = None,
    ) -> None:
        self.registrations = registrations or {}
        self.sites = sites or {}
        self.twins = twins or {}
        self.failing = failing
        self.rejects = rejects  # a name the service cannot parse inside a list
        self.paths: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        self.paths.append(path)
        if self.failing and path.startswith(self.failing):
            return httpx.Response(500, json={"error": "down"})
        kind, _, rest = path.lstrip("/").partition("/")
        if kind == "eis":
            rows = [_reg(i, e) for i in rest.split(",") for e in self.registrations.get(i, [])]
        elif kind == "sites":
            rows = [self.sites[i] for i in rest.split(",") if i in self.sites]
        else:
            names, _, state = rest.rpartition("/")
            if kind == "twins" and self.rejects and self.rejects in names.split(","):
                return httpx.Response(500, json={"error": "The query could not be parsed."})
            rows = [
                r
                for n in names.split(",")
                if kind == "twins"
                for r in self.twins.get((n, state), [])
            ]
            if kind == "twin":
                rows = self.twins.get((names, state), [])
        return httpx.Response(200, json=rows)

    def resolve(self, *frs_ids: str) -> list[EmissionRecord]:
        client = EfserviceClient(
            EF,
            httpx.Client(transport=httpx.MockTransport(self.handle)),
            lambda _: None,
        )
        return EisResolver(client, SETTINGS)([emission_record(i, 1.0) for i in frs_ids])


def _ids(records: list[EmissionRecord]) -> list[list[str]]:
    return [r["eis_ids"] for r in records]


def test_distance_is_the_great_circle_distance() -> None:
    assert distance_km(0.0, 0.0, 0.0, 0.0) == 0.0
    assert (
        round(distance_km(0.0, 0.0, 0.0, 1.0), 1) == 111.2
    )  # one degree of longitude at the equator
    assert round(distance_km(30.205556, -91.006944, 30.205046, -91.005453)) == 0  # ~150 m


def test_registrations_are_found_in_bulk_and_distinct() -> None:
    service = Service({A: ["111", "111", "222"], B: ["333"]})
    records = service.resolve(A, B)
    assert _ids(records) == [["111", "222"], ["333"]]
    assert [r["eis_note"] for r in records] == [None, None]
    assert service.paths == [f"/eis/{A},{B}"]


def test_many_facilities_share_a_request_up_to_the_batch_size() -> None:
    service = Service({A: ["1"], B: ["2"], C: ["3"]})
    assert _ids(service.resolve(A, B, C)) == [["1"], ["2"], ["3"]]
    assert [p for p in service.paths if p.startswith("/eis/")][:2] == [f"/eis/{A},{B}", f"/eis/{C}"]


def test_a_record_without_registration_says_so_when_it_has_no_twin() -> None:
    service = Service({A: ["1"]}, sites={B: _site(B)}, twins={("PLANT ONE", "TX"): [_site(B)]})
    records = service.resolve(A, B)
    assert _ids(records) == [["1"], []]
    assert (
        records[1]["eis_note"]
        == f"FRS ID {B} has no EIS registration, and no other FRS record of the same site was found"
    )


def test_the_ids_of_the_one_nearby_twin_with_registrations_are_borrowed() -> None:
    twins = [_site(B), _site(TWIN, lat=30.001), _site(FAR, lat=30.1)]
    service = Service(
        {TWIN: ["77"], FAR: ["88"]},
        sites={B: _site(B)},
        twins={("PLANT ONE", "TX"): twins},
    )
    record = service.resolve(B)[0]
    assert record["eis_ids"] == ["77"]
    assert record["eis_note"] is not None
    assert record["eis_note"].startswith(
        f"EIS IDs are those of FRS ID {TWIN}, the same site name 111 m away",
    )
    assert f"since FRS ID {B} has no EIS registration" in record["eis_note"]
    assert f"/eis/{TWIN}" in service.paths and FAR not in "".join(
        p for p in service.paths if p.startswith("/eis/")
    )


@pytest.mark.parametrize(
    ("twin_row", "why"),
    [
        (
            _site(TWIN, name="PLANT TWO", lat=30.001),
            "no other FRS record",
        ),  # another name: not the site
        (
            _site(TWIN, state="LA", lat=30.001),
            "no other FRS record",
        ),  # service answered another state
        (_site(TWIN, lat=30.001, lon="east"), "no other FRS record"),  # unusable coordinates
    ],
)
def test_a_twin_must_match_name_and_have_coordinates(twin_row: Row, why: str) -> None:
    service = Service({TWIN: ["77"]}, sites={B: _site(B)}, twins={("PLANT ONE", "TX"): [twin_row]})
    record = service.resolve(B)[0]
    assert record["eis_ids"] == [] and why in (record["eis_note"] or "")


def test_the_twins_of_several_facilities_have_their_registrations_read_together() -> None:
    sites = {B: _site(B), C: _site(C, name="PLANT TWO", lat=31.0)}
    twins = {
        ("PLANT ONE", "TX"): [_site(TWIN, lat=30.001)],
        ("PLANT TWO", "TX"): [_site(FAR, name="PLANT TWO", lat=31.001)],
    }
    service = Service({TWIN: ["77"], FAR: ["88"]}, sites=sites, twins=twins)
    assert _ids(service.resolve(B, C)) == [["77"], ["88"]]
    registrations = [p for p in service.paths if p.startswith("/eis/")]
    assert registrations == [f"/eis/{B},{C}", f"/eis/{TWIN},{FAR}"]  # own, then every twin
    assert sum(p.startswith("/twins/") for p in service.paths) == 1  # one request, both names


def test_two_twins_with_registrations_are_ambiguous_and_none_is_used() -> None:
    twins = [_site(TWIN, lat=30.001), _site(C, lat=30.002)]
    service = Service(
        {TWIN: ["77"], C: ["99"]},
        sites={B: _site(B)},
        twins={("PLANT ONE", "TX"): twins},
    )
    record = service.resolve(B)[0]
    assert record["eis_ids"] == []
    assert "2 have their own" in (record["eis_note"] or "")


def test_a_twin_without_registrations_gives_nothing() -> None:
    service = Service(
        {},
        sites={B: _site(B)},
        twins={("PLANT ONE", "TX"): [_site(TWIN, lat=30.001)]},
    )
    record = service.resolve(B)[0]
    assert record["eis_ids"] == [] and "none has one" in (record["eis_note"] or "")


def test_a_facility_without_a_site_row_cannot_be_matched() -> None:
    record = Service({}).resolve(B)[0]
    assert record["eis_ids"] == [] and record["eis_note"] == f"FRS ID {B} has no EIS registration"


def test_a_failed_registration_request_leaves_everyone_without_ids_and_a_note() -> None:
    service = Service({A: ["1"]}, failing="/eis/")
    records = service.resolve(A, B)
    assert _ids(records) == [[], []]
    assert all("could not be looked up" in (r["eis_note"] or "") for r in records)
    assert not any(p.startswith("/sites/") for p in service.paths)


def test_the_inputs_are_not_changed() -> None:
    record = emission_record(A, 1.0)
    EisResolver(
        EfserviceClient(
            EF,
            httpx.Client(transport=httpx.MockTransport(Service({A: ["1"]}).handle)),
            lambda _: None,
        ),
        SETTINGS,
    )([record])
    assert record["eis_ids"] == []


def test_rows_for_ids_not_asked_or_without_digits_are_ignored() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[_reg(C, "5"), _reg(A, "x"), _reg(A, None), {"registry_id": A}],
        )

    client = EfserviceClient(
        EF,
        httpx.Client(transport=httpx.MockTransport(handle)),
        lambda _: None,
    )
    records = EisResolver(client, SETTINGS)([emission_record(A, 1.0)])
    assert records[0]["eis_ids"] == []


def _many(count: int) -> tuple[dict[str, Row], dict[tuple[str, str], list[Row]], list[str]]:
    ids = [f"1100000001{i:02d}" for i in range(count)]
    sites = {i: _site(i, name=f"PLANT {n}") for n, i in enumerate(ids)}
    twins = {(f"PLANT {n}", "TX"): [sites[i]] for n, i in enumerate(ids)}
    return sites, twins, ids


def test_twin_searches_go_by_batch_of_names_not_by_facility() -> None:
    sites, twins, ids = _many(5)
    service = Service({}, sites=sites, twins=twins)
    service.resolve(*ids)
    searches = [p for p in service.paths if p.startswith("/twin")]
    assert len(searches) == 3  # 5 names: lists of 2 and 2, and the last one alone
    assert sum(p.startswith("/twins/") for p in searches) == 2


def test_a_name_the_service_cannot_parse_is_not_searched() -> None:
    name = "PLANT, ONE"
    twin = _site(TWIN, name=name, lat=30.001)
    service = Service({TWIN: ["77"]}, sites={B: _site(B, name=name)}, twins={(name, "TX"): [twin]})
    record = service.resolve(B)[0]
    assert record["eis_ids"] == []
    assert not [p for p in service.paths if p.startswith("/twin")]


def test_a_rejected_batch_is_split_until_the_bad_name_is_alone() -> None:
    sites, twins, ids = _many(4)
    twins[("PLANT 3", "TX")] = [sites[ids[3]], _site(TWIN, name="PLANT 3", lat=30.001)]
    service = Service({TWIN: ["77"]}, sites=sites, twins=twins, rejects="PLANT 1")
    records = service.resolve(*ids)
    assert records[3]["eis_ids"] == ["77"]  # the other names were still searched
    assert records[1]["eis_ids"] == []  # PLANT 1 alone is rejected only inside a list
    assert any(p.startswith("/twin/PLANT 1/") for p in service.paths)


def test_a_failing_twin_search_leaves_a_note_and_no_exception() -> None:
    service = Service({}, sites={B: _site(B)}, failing="/twin")
    record = service.resolve(B)[0]
    assert record["eis_ids"] == [] and "no other FRS record" in (record["eis_note"] or "")


def test_names_with_characters_the_service_rejects_cost_no_request() -> None:
    odd = ["A&B CO", "O'BRIEN CO", "PLANT (USA)"]
    sites = {f"11000000020{n}": _site(f"11000000020{n}", name=name) for n, name in enumerate(odd)}
    service = Service({}, sites=sites, twins={})
    service.resolve(*sites)
    assert not [p for p in service.paths if p.startswith("/twin")]
