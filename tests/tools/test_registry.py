"""Tests for the tool and prompt registries."""

from __future__ import annotations

import pytest

from tools.registry import ToolRegistry, get_all_tools


def test_all_tools_registered_with_docstrings() -> None:
    tools = get_all_tools()
    assert {t.name for t in tools} == {
        "fetch_chemical_properties",
        "find_tri_category",
        "find_tri_read_across_surrogate",
        "query_emissions_inventory",
        "fetch_facility_industry",
        "lookup_scc_process_description",
        "fetch_stack_parameters_from_nei",
        "fetch_stack_parameters_from_scc",
        "get_meteorological_boundary",
        "get_population_receptors",
        "calculate_exposure_metrics",
        "assess_facilities",
        "check_job_status",
    }
    assert all(t.description for t in tools)


def test_duplicate_registration_rejected() -> None:
    reg = ToolRegistry()
    tool = get_all_tools()[0]
    reg.register(tool)
    with pytest.raises(ValueError):
        reg.register(tool)


def test_the_shipped_heavy_tools_are_registered() -> None:
    from config.worker import check_heavy_tools, get_worker_settings

    check_heavy_tools(get_worker_settings(), (tool.name for tool in get_all_tools()))


def test_a_misspelt_heavy_tool_fails_when_the_registry_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    import tools.registry as module
    from config.worker import get_worker_settings

    bad = replace(get_worker_settings(), heavy_tools=("assess_facilitiez",))
    monkeypatch.setattr(module, "get_worker_settings", lambda: bad)
    with pytest.raises(ValueError, match="assess_facilitiez"):
        module._build_default_registry()  # pyright: ignore[reportPrivateUsage]


def test_every_job_runner_is_a_registered_tool() -> None:
    from tools.registry import get_job_runners

    names = {tool.name for tool in get_all_tools()}
    assert set(get_job_runners()) <= names and "assess_facilities" in get_job_runners()


def _heavy_registry(
    monkeypatch: pytest.MonkeyPatch,
    heavy_tools: tuple[str, ...] = ("assess_facilities",),
) -> list[str]:
    from dataclasses import replace

    import tools.registry as module
    from config.worker import get_worker_settings

    heavy = replace(get_worker_settings(), heavy_tools=heavy_tools)
    monkeypatch.setattr(module, "get_worker_settings", lambda: heavy)
    return [tool.name for tool in module._build_default_registry().all()]  # pyright: ignore[reportPrivateUsage]


def test_a_heavy_tool_keeps_its_name_schema_and_docstring_as_a_submitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    import tools.registry as module
    from config.worker import get_worker_settings

    heavy = replace(get_worker_settings(), heavy_tools=("assess_facilities",))
    monkeypatch.setattr(module, "get_worker_settings", lambda: heavy)
    built = module._build_default_registry()  # pyright: ignore[reportPrivateUsage]
    original = get_all_tools()
    plain = next(t for t in original if t.name == "assess_facilities")
    submitter = built.get("assess_facilities")
    assert submitter is not plain
    assert submitter.args_schema is plain.args_schema
    assert submitter.description == plain.description


def test_check_job_status_exists_only_with_a_heavy_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = _heavy_registry(monkeypatch, heavy_tools=())
    assert "check_job_status" not in plain
    names = _heavy_registry(monkeypatch)
    assert names.count("check_job_status") == 1
    assert names.count("assess_facilities") == 1 and len(names) == len(plain) + 1


def test_a_heavy_tool_without_a_preflight_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.registry as module

    monkeypatch.setattr(module, "PREFLIGHTS", {})
    with pytest.raises(ValueError, match="assess_facilities"):
        _heavy_registry(monkeypatch)
