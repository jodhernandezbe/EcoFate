"""Central tool registry: every tool the agent can bind, exported as one list.

Building it also checks that ``[worker].heavy_tools`` names only registered tools (``config``
cannot import the registry), so a misspelt name fails at start-up. A heavy tool is registered as
its background *submitter* (same name, schema and docstring; the call queues a job), and the quick
tool ``check_job_status`` joins the list; with no heavy tool the registry is as it always was.
"""

from __future__ import annotations

from collections.abc import Mapping

from langchain_core.tools import BaseTool

from config.worker import check_heavy_tools, get_worker_settings
from tools.assessment import TOOLS as ASSESSMENT_TOOLS
from tools.assessment import check_before_job, run_assessment_job
from tools.emissions import TOOLS as EMISSIONS_TOOLS
from tools.exposure import TOOLS as EXPOSURE_TOOLS
from tools.informatics import TOOLS as INFORMATICS_TOOLS
from tools.jobs import TOOLS as JOB_TOOLS
from tools.jobs import heavy_submitter
from tools.jobs.submit import Preflight
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


# What each heavy tool settles before a job may be queued (invalid input, missing values).
PREFLIGHTS: Mapping[str, Preflight] = {"assess_facilities": check_before_job}


def _as_submitters(tools: list[BaseTool], heavy: tuple[str, ...]) -> list[BaseTool]:
    """The tools, each heavy one replaced by its submitter; ``check_job_status`` is added when
    there is a heavy tool.

    Raises:
        ValueError: A heavy tool has no preflight.
    """
    if not heavy:
        return tools
    lacking = sorted(name for name in heavy if name not in PREFLIGHTS)
    if lacking:
        raise ValueError(f"heavy tools without a job preflight: {', '.join(lacking)}")
    wrapped = [heavy_submitter(t, PREFLIGHTS[t.name]) if t.name in heavy else t for t in tools]
    return [*wrapped, *JOB_TOOLS]


def _build_default_registry() -> ToolRegistry:
    registry, settings = ToolRegistry(), get_worker_settings()
    tools = [*INFORMATICS_TOOLS, *EMISSIONS_TOOLS, *EXPOSURE_TOOLS, *ASSESSMENT_TOOLS]
    check_heavy_tools(settings, (tool.name for tool in tools))
    registry.register(*_as_submitters(tools, settings.heavy_tools))
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
