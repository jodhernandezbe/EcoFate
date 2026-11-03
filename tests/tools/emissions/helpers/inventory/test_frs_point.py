"""Tests for tools.emissions.helpers.inventory.frs_point."""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
import pytest

from config.efservice import EfserviceSettings
from config.frs_point import FrsPointSettings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.inventory.frs_point import FrsLocator
from tools.emissions.helpers.inventory.reduce import Location

SETTINGS = FrsPointSettings("https://frs.test", "/p/{frs_ids}", "id", "lat", "lon", 2)
EF = EfserviceSettings("https://frs.test", 0.0, 5.0, 0, 0.0)
A, B, C = "110000000001", "110000000002", "110000000003"


def _row(frs_id: str, lat: object = 1.0, lon: object = -1.0) -> dict[str, object]:
    return {"id": frs_id, "lat": lat, "lon": lon}


def _locator(
    answer: Callable[[list[str]], object] | object,
    status: int = 200,
) -> tuple[FrsLocator, list[list[str]]]:
    asked: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.path.removeprefix("/p/").split(",")
        asked.append(ids)
        return httpx.Response(status, json=answer(ids) if callable(answer) else answer)

    client = EfserviceClient(
        EF,
        httpx.Client(transport=httpx.MockTransport(handler)),
        lambda _: None,
    )
    return FrsLocator(client, SETTINGS), asked


def test_a_point_is_returned_for_each_facility_asked() -> None:
    locator, asked = _locator([_row(A, 10.5, -20.25), _row(B, 3.0, -4.0)])
    assert locator([A, B]) == {A: Location(10.5, -20.25), B: Location(3.0, -4.0)}
    assert asked == [[A, B]]


def test_many_facilities_share_a_request_up_to_the_batch_size() -> None:
    locator, asked = _locator(lambda ids: [_row(i) for i in ids])
    assert set(locator([A, B, C])) == {A, B, C}
    assert asked == [[A, B], [C]]


def test_duplicates_are_asked_once() -> None:
    locator, asked = _locator(lambda ids: [_row(i) for i in ids])
    locator([A, A, B])
    assert asked == [[A, B]]


def test_answers_are_remembered_across_calls() -> None:
    locator, asked = _locator(lambda ids: [_row(i) for i in ids])
    locator([A])
    locator([A, B])
    assert asked == [[A], [B]]


def test_a_facility_the_service_does_not_know_is_left_out_and_not_asked_again() -> None:
    locator, asked = _locator([_row(A)])
    assert locator([A, B]) == {A: Location(1.0, -1.0)}
    locator([B])
    assert len(asked) == 1


def test_a_row_for_a_facility_that_was_not_asked_is_ignored() -> None:
    locator, _ = _locator([_row(C)])
    assert locator([A]) == {}


def test_the_first_usable_point_of_a_facility_wins() -> None:
    locator, _ = _locator([_row(A, None, None), _row(A, 2.0, -2.0), _row(A, 9.0, -9.0)])
    assert locator([A]) == {A: Location(2.0, -2.0)}


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(91.0, -1.0), (1.0, 181.0), (True, -1.0), ("1", "-1"), (1.0, None)],
)
def test_unusable_points_are_left_out(lat: object, lon: object) -> None:
    locator, _ = _locator([_row(A, lat, lon)])
    assert locator([A]) == {}


@pytest.mark.parametrize("bad", ["", "abc", "11-00"])
def test_an_invalid_id_makes_no_request(bad: str) -> None:
    locator, asked = _locator([])
    assert locator([bad]) == {}
    assert asked == []


def test_a_failed_request_leaves_its_facilities_out_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    locator, _ = _locator({"error": "x"}, status=500)
    with caplog.at_level(logging.WARNING):
        assert locator([A, B]) == {}
    assert "could not be read" in caplog.text


def test_one_failed_batch_does_not_lose_the_others() -> None:
    def answer(ids: list[str]) -> object:
        return [_row(i) for i in ids]

    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.path.removeprefix("/p/").split(",")
        calls.append(ids)
        return httpx.Response(500) if A in ids else httpx.Response(200, json=answer(ids))

    client = EfserviceClient(
        EF,
        httpx.Client(transport=httpx.MockTransport(handler)),
        lambda _: None,
    )
    assert set(FrsLocator(client, SETTINGS)([A, B, C])) == {C}
