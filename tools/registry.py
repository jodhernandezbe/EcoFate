"""Central tool registry: every tool the agent can bind, exported as one list.

Building it also checks that ``[worker].heavy_tools`` names only registered tools (``config``
cannot import the registry), so a misspelt name fails at start-up.
"""

from __future__ import annotations

from collections.abc import Mapping

from langchain_core.tools import BaseTool

from config.worker import check_heavy_tools, get_worker_settings
from tools.assessment import TOOLS as ASSESSMENT_TOOLS
from tools.assessment import run_assessment_job
from tools.emissions import TOOLS as EMISSIONS_TOOLS
from tools.exposure import TOOLS as EXPOSURE_TOOLS
from tools.informatics import TOOLS as INFORMATICS_TOOLS
from tools.schemas import JobRunner


class ToolRegistry:
    """Ordered collection of tools, keyed by tool name."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, *tools: BaseTool) -> None:
        """Add tools; raises ``ValueError`` on duplicate names."""
        for t in tools:
            if t.name in self._tools:
                raise ValueError(f"Tool already registered: {t.name}")
            self._tools[t.name] = t

    def get(self, name: str) -> BaseTool:
        """Return the tool called ``name``; raises ``KeyError`` if unknown."""
        return self._tools[name]

    def all(self) -> list[BaseTool]:
        """Return all registered tools in registration order."""
        return list(self._tools.values())


def _build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        *INFORMATICS_TOOLS,
        *EMISSIONS_TOOLS,
        *EXPOSURE_TOOLS,
        *ASSESSMENT_TOOLS,
    )
    check_heavy_tools(get_worker_settings(), (tool.name for tool in registry.all()))
    return registry


registry: ToolRegistry = _build_default_registry()

ALL_TOOLS: list[BaseTool] = registry.all()


def get_all_tools() -> list[BaseTool]:
    """Return every registered tool, ready to pass to ``model.bind_tools``."""
    return registry.all()


# The heavy tools as a background job runs them (tool name -> runner of its stored input).
JOB_RUNNERS: Mapping[str, JobRunner] = {"assess_facilities": run_assessment_job}


def get_job_runners() -> Mapping[str, JobRunner]:
    """The runner of each tool that can run as a background job, by tool name."""
    return JOB_RUNNERS
