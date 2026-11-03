"""Tests for the stack parameter tools."""

from __future__ import annotations

import gzip
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from config.efservice import get_efservice_settings
from config.stack import StackSettings, load_stack_settings
from tools.emissions import stack
from tools.emissions.stack import fetch_stack_parameters_from_nei, fetch_stack_parameters_from_scc


def test_nei_schema_and_description() -> None:
    tool = fetch_stack_parameters_from_nei
    assert tool.name == "fetch_stack_parameters_from_nei"
    assert set(tool.args) == {"frs_id", "eis_ids"}
    description = tool.description
    assert "fetch_stack_parameters_from_scc" in description
    assert "first choice" in description
    assert "ALL candidates together" in description
    for text in ("m above ground", "m/s", "(K)", "never averaged"):
        assert text in description


def _nei_settings(tmp_path: Path, rows: str) -> StackSettings:
    (tmp_path / "nei_stacks_1.csv.gz").write_bytes(
        gzip.compress(("eis_id,stkhgt,stkdiam,stkvel,stktemp\n" + rows).encode()),
    )
    base = load_stack_settings()
    return replace(base, nei=replace(base.nei, directory=tmp_path, prefix_digits=1))


def test_nei_tool_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frs = "999999999999"
    body = [{"registry_id": frs, "pgm_sys_acrnm": "EIS", "pgm_sys_id": "1000001"}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    monkeypatch.setattr(stack, "_open_client", lambda: httpx.Client(transport=transport))
    ef = replace(get_efservice_settings(), delay_seconds=0.0)
    monkeypatch.setattr(stack, "get_efservice_settings", lambda: ef)
    nei = _nei_settings(tmp_path, "1000001,10,3,10,200\n1000001,20,3,10,200\n")
    monkeypatch.setattr(stack, "get_stack_settings", lambda: nei)
    result = fetch_stack_parameters_from_nei.invoke({"frs_id": frs})
    assert result["eis_ids"] == ["1000001"]
    assert [round(c["stack_height"] / 0.3048) for c in result["candidates"]] == [10, 20]
    assert all(c["source"] == "NEI" for c in result["candidates"])


def test_nei_tool_uses_the_eis_ids_given_without_a_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    monkeypatch.setattr(
        stack,
        "_open_client",
        lambda: httpx.Client(transport=httpx.MockTransport(fail)),
    )
    nei = _nei_settings(tmp_path, "1000001,10,3,10,200\n")
    monkeypatch.setattr(stack, "get_stack_settings", lambda: nei)
    result = fetch_stack_parameters_from_nei.invoke(
        {"frs_id": "999999999999", "eis_ids": ["1000001"]},
    )
    assert result["eis_ids"] == ["1000001"]
    assert len(result["candidates"]) == 1
    assert set(fetch_stack_parameters_from_nei.args) == {"frs_id", "eis_ids"}


@pytest.mark.parametrize("frs", ["abc", ""])
def test_nei_tool_with_invalid_frs_id_makes_no_request(
    frs: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    monkeypatch.setattr(
        stack,
        "_open_client",
        lambda: httpx.Client(transport=httpx.MockTransport(fail)),
    )
    result = fetch_stack_parameters_from_nei.invoke({"frs_id": frs})
    assert result["candidates"] == []
    assert "fetch_stack_parameters_from_scc" in result["warnings"][-1]


def test_scc_schema_and_description() -> None:
    tool = fetch_stack_parameters_from_scc
    assert tool.name == "fetch_stack_parameters_from_scc"
    assert set(tool.args) == {"scc_code"}
    description = tool.description
    assert "ONLY after `fetch_stack_parameters_from_nei` returned no values" in description
    assert "not measurements" in description
    for text in ("m above ground", "m/s", "K", '"PSTK"', '"AirToxScreen global default"'):
        assert text in description


def test_scc_tool_uses_configured_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_stack_settings()
    missing = replace(settings, pstk=replace(settings.pstk, path=tmp_path / "absent.csv"))
    monkeypatch.setattr(stack, "get_stack_settings", lambda: missing)
    result = fetch_stack_parameters_from_scc.invoke({"scc_code": "99900001"})
    assert result["source"] == "AirToxScreen global default"
    assert result["stack_height"] == settings.global_fallback["stack_height"]


@pytest.mark.parametrize("arguments", [{}, {"scc_code": None}])
def test_scc_tool_without_scc_gives_global_default(arguments: dict[str, object]) -> None:
    settings = load_stack_settings()
    result = fetch_stack_parameters_from_scc.invoke(arguments)
    assert result["source"] == "AirToxScreen global default"
    assert result["scc"] is None
    assert result["exit_temperature"] == settings.global_fallback["exit_temperature"]
    assert "no SCC was given" in result["warnings"][0]


def test_scc_is_optional_in_the_schema() -> None:
    schema = fetch_stack_parameters_from_scc.args["scc_code"]
    assert schema.get("default", "missing") is None
    assert "Omit it" in fetch_stack_parameters_from_scc.description


@pytest.mark.parametrize("code", ["99900001", " 99900001 ", 99900001])
def test_scc_tool_accepts_text_or_number(
    code: str | int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pstk.csv"
    path.write_text("fips,scc,stkhgt,stkdiam,stkvel,stktemp\n0,99900001,10,1,5,400\n")
    settings = load_stack_settings()
    patched = replace(settings, pstk=replace(settings.pstk, path=path))
    monkeypatch.setattr(stack, "get_stack_settings", lambda: patched)
    result = fetch_stack_parameters_from_scc.invoke({"scc_code": code})
    assert (result["source"], result["scc"], result["stack_height"]) == ("PSTK", "99900001", 10.0)


def test_scc_tool_rejects_a_word() -> None:
    result = fetch_stack_parameters_from_scc.invoke({"scc_code": "abc"})
    assert result["source"] == "AirToxScreen global default"
    assert "is invalid" in result["warnings"][0]
