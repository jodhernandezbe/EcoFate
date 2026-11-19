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
