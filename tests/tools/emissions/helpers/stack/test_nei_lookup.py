"""Tests for tools.emissions.helpers.stack.nei_lookup (no network: an httpx mock transport)."""

from __future__ import annotations

import gzip
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from config.efservice import load_efservice_settings, load_frs_settings
from config.stack import StackSettings, load_stack_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.stack.nei_lookup import nei_stack_result
from tools.schemas import NeiStackResult

FRS = "999999999999"
EFSERVICE = replace(load_efservice_settings(), base_url="https://frs.test", delay_seconds=0.0)
FRS_SETTINGS = replace(load_frs_settings(), eis_path="/f/{frs_id}/EIS/JSON")
HEADER = "eis_id,stkhgt,stkdiam,stkvel,stktemp\n"


def _settings(tmp_path: Path, rows: str) -> StackSettings:
    (tmp_path / "nei_stacks_1.csv.gz").write_bytes(gzip.compress((HEADER + rows).encode()))
    base = load_stack_settings()
    return replace(base, nei=replace(base.nei, directory=tmp_path, prefix_digits=1))


def _run(
    tmp_path: Path,
    body: object,
    rows: str = "",
    frs: str | int = FRS,
) -> tuple[NeiStackResult, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    client = EfserviceClient(
        EFSERVICE,
        httpx.Client(transport=httpx.MockTransport(handler)),
        lambda _s: None,
    )
    result = nei_stack_result(frs, client, FRS_SETTINGS, _settings(tmp_path, rows), None)
    return result, seen


def _eis(*ids: str) -> list[dict[str, str]]:
    return [{"registry_id": FRS, "pgm_sys_acrnm": "EIS", "pgm_sys_id": i} for i in ids]


def test_frs_id_to_candidates(tmp_path: Path) -> None:
    result, seen = _run(tmp_path, _eis("1000001"), "1000001,10,3,10,200\n")
    assert result["eis_ids"] == ["1000001"]
    assert result["total_candidates"] == 1
    assert result["warnings"] == []
    (candidate,) = result["candidates"]
    assert candidate["source"] == "NEI"
    assert candidate["scc"] is None
    assert candidate["warnings"] == []
    assert candidate["stack_height"] == pytest.approx(10 * 0.3048)
    assert [str(r.url) for r in seen] == [f"https://frs.test/f/{FRS}/EIS/JSON"]


def test_stacks_of_several_eis_ids_are_candidates_together(tmp_path: Path) -> None:
    rows = "1000001,10,3,10,200\n1000002,20,3,10,200\n"
    result, _ = _run(tmp_path, _eis("1000001", "1000002"), rows)
    assert result["eis_ids"] == ["1000001", "1000002"]
    assert len(result["candidates"]) == 2


def test_integer_frs_id_is_accepted(tmp_path: Path) -> None:
    body = [{"registry_id": "12", "pgm_sys_acrnm": "EIS", "pgm_sys_id": "1000001"}]
    result, _ = _run(tmp_path, body, "1000001,10,3,10,200\n", frs=12)
    assert len(result["candidates"]) == 1


def test_no_eis_id_points_to_the_scc_tool(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, [], "1000001,10,3,10,200\n")
    assert (result["eis_ids"], result["candidates"], result["total_candidates"]) == ([], [], 0)
    assert "has no EIS registration" in result["warnings"][0]
    assert "fetch_stack_parameters_from_scc" in result["warnings"][-1]


def test_eis_id_without_nei_rows_points_to_the_scc_tool(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, _eis("1999999"), "1000001,10,3,10,200\n")
    assert result["eis_ids"] == ["1999999"]
    assert result["candidates"] == []
    assert "no stack data for EIS ID 1999999" in result["warnings"][0]
    assert "fetch_stack_parameters_from_scc" in result["warnings"][-1]


def test_only_invalid_rows_point_to_the_scc_tool(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, _eis("1000001"), "1000001,,3,10,200\n")
    assert result["candidates"] == []
    assert "1 NEI stack row(s) were ignored" in result["warnings"][0]
    assert "fetch_stack_parameters_from_scc" in result["warnings"][-1]


def test_invalid_frs_id_makes_no_request(tmp_path: Path) -> None:
    result, seen = _run(tmp_path, _eis("1000001"), frs="abc")
    assert result["candidates"] == []
    assert "is invalid" in result["warnings"][0]
    assert seen == []


def test_frs_failure_is_a_warning(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, {"error": "x"})
    assert result["candidates"] == []
    assert "could not be looked up" in result["warnings"][0]


def test_eis_ids_given_skip_the_frs_lookup(tmp_path: Path) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    client = EfserviceClient(
        EFSERVICE,
        httpx.Client(transport=httpx.MockTransport(fail)),
        lambda _s: None,
    )
    rows = "1000001,10,3,10,200\n"
    result = nei_stack_result(
        FRS,
        client,
        FRS_SETTINGS,
        _settings(tmp_path, rows),
        None,
        eis_ids=["1000001", " ", "x", 1000001],
    )
    assert result["eis_ids"] == ["1000001"]
    assert len(result["candidates"]) == 1


def test_an_empty_eis_list_falls_back_to_the_frs_lookup(tmp_path: Path) -> None:
    client = EfserviceClient(
        EFSERVICE,
        httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_eis("1000001"))),
        ),
        lambda _s: None,
    )
    result = nei_stack_result(
        FRS,
        client,
        FRS_SETTINGS,
        _settings(tmp_path, "1000001,10,3,10,200\n"),
        None,
        eis_ids=[],
    )
    assert result["eis_ids"] == ["1000001"]
