"""Tests for tools.emissions.helpers.stack.frs (no network: an httpx mock transport).

Identifiers are obviously fake (all-nines or sequential), not real facilities.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import httpx
import pytest

from config.efservice import load_efservice_settings, load_frs_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.stack.frs import EisLookup, eis_ids_for_frs

FRS = "999999999999"
SETTINGS = replace(load_frs_settings(), eis_path="/f/{frs_id}/EIS/JSON")
EFSERVICE = replace(
    load_efservice_settings(),
    base_url="https://frs.test",
    delay_seconds=0.0,
    max_retries=0,
)


def _row(
    eis: object = "1234567",
    registry: object = FRS,
    program: object = "EIS",
) -> dict[str, object]:
    return {"registry_id": registry, "pgm_sys_acrnm": program, "pgm_sys_id": eis}


def _lookup(
    body: object,
    frs: str | int = FRS,
    status: int = 200,
) -> tuple[EisLookup, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    client = EfserviceClient(
        EFSERVICE,
        httpx.Client(transport=httpx.MockTransport(handler)),
        lambda _s: None,
    )
    return eis_ids_for_frs(frs, client, SETTINGS), seen


def test_one_eis_row() -> None:
    result, seen = _lookup([_row()])
    assert (result.frs_id, result.eis_ids, result.warnings) == (FRS, ("1234567",), ())
    assert [str(r.url) for r in seen] == [f"https://frs.test/f/{FRS}/EIS/JSON"]


def test_several_rows_are_distinct_and_ordered() -> None:
    rows = [_row("222"), _row("111"), _row("222")]
    assert _lookup(rows)[0].eis_ids == ("222", "111")


def test_integer_and_padded_frs_ids_are_accepted() -> None:
    assert _lookup([_row("1", registry="12")], 12)[0].eis_ids == ("1",)
    assert _lookup([_row()], f" {FRS} ")[0].frs_id == FRS


def test_integer_eis_id_in_the_response() -> None:
    assert _lookup([_row(eis=1234567)])[0].eis_ids == ("1234567",)


def test_no_registration_warns() -> None:
    result, _ = _lookup([])
    assert result.eis_ids == ()
    assert result.warnings == (f"FRS ID {FRS} has no EIS registration",)


@pytest.mark.parametrize(
    "row",
    [
        _row(registry="888888888888"),
        _row(program="TRI"),
        _row(eis=None),
        _row(eis=""),
        _row(eis="12a"),
        _row(eis=True),
        _row(eis=["1"]),
        {"registry_id": FRS},
    ],
)
def test_mismatched_or_incomplete_rows_are_ignored(row: dict[str, object]) -> None:
    result, _ = _lookup([row, _row("555")])
    assert result.eis_ids == ("555",)


def test_program_match_ignores_case_and_spaces() -> None:
    assert _lookup([_row(program=" eis ")])[0].eis_ids == ("1234567",)


@pytest.mark.parametrize("frs", ["", "   ", "12-3", "abc", "1.5", -1, True])
def test_invalid_frs_id_makes_no_request(frs: str | int) -> None:
    result, seen = _lookup([_row()], frs)
    assert (result.frs_id, result.eis_ids) == (None, ())
    assert "is invalid" in result.warnings[0]
    assert seen == []


@pytest.mark.parametrize("status", [404, 500])
def test_http_failure_is_a_warning_not_an_exception(
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result, _ = _lookup([], status=status)
    assert result.eis_ids == ()
    assert "could not be looked up" in result.warnings[0]
    assert "EIS lookup" in caplog.text


@pytest.mark.parametrize("body", [{"error": "x"}, "text", [1, 2]])
def test_unexpected_shape_is_a_warning(body: object) -> None:
    result, _ = _lookup(body)
    assert result.eis_ids == ()
    assert "could not be looked up" in result.warnings[0]


def test_example_response_shape() -> None:
    """A row shaped like the real response, with extra fields and fake identifiers."""
    row: dict[str, object] = {
        "registry_id": FRS,
        "pgm_sys_acrnm": "EIS",
        "pgm_sys_id": "1234567",
        "primary_name": "EXAMPLE FACILITY",
        "state_code": "XX",
        "source_of_data": "EIS",
    }
    assert _lookup([row])[0].eis_ids == ("1234567",)
