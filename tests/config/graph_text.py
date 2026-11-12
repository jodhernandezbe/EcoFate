"""Synthetic ``[ui.exposure_graph]`` text for settings tests (every key, placeholder labels)."""

from __future__ import annotations

from config import exposure_graph as graph


def _table(keys: tuple[str, ...], value: str = "x") -> str:
    return "\n".join(f'{key} = "{value} {key}"' for key in keys)


def _nodes() -> str:
    special = {"stack": "Stack {number}", "age_band": "Aged {band}"}
    return "\n".join(f'{k} = "{special.get(k, k)}"' for k in graph.NODES)


GRAPH = f"""
[ui.exposure_graph]
source = "Source"

[ui.exposure_graph.lanes]
{_table(graph.LANES)}

[ui.exposure_graph.nodes]
{_nodes()}

[ui.exposure_graph.facts]
{_table(graph.FACTS)}

[ui.exposure_graph.tiers]
{_table(graph.TIERS)}

[ui.exposure_graph.settings]
{_table(graph.SETTINGS)}

[ui.exposure_graph.estimators]
{_table(graph.ESTIMATORS)}

[ui.exposure_graph.volatilities]
{_table(graph.VOLATILITIES)}

[ui.exposure_graph.evidences]
{_table(graph.EVIDENCES)}

[ui.exposure_graph.flags]
{_table(graph.FLAGS)}

[ui.exposure_graph.variants]
{_table(graph.VARIANTS)}

[ui.exposure_graph.reasons]
{_table(graph.REASONS)}

[ui.exposure_graph.quantities]
""" + "\n".join(f'{k} = {{ label = "L {k}", unit = "u" }}' for k in graph.QUANTITIES)
