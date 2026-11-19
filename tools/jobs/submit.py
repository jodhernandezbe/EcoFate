"""The submitter of a heavy tool: the same tool for the model, but its call starts a job.

``heavy_submitter(tool, preflight)`` wraps a registered tool: same name, argument schema and
docstring (plus a paragraph saying it runs in the background). Its call settles what must be
settled before any work (the tool's ``preflight``: invalid input, values the user must be asked
for) and returns that result exactly as the tool would; otherwise it records a job, queues it
and answers at once with its id, ``queued`` and its position. The user and thread of the job come
from the run's configuration (the authenticated turn), never from the arguments. With no job
system provided (command line, evaluations) the call runs the tool itself, as without a wrapper.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import cast

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

from tools.jobs.port import JobUnavailableError, current_port, job_scope
from tools.schemas import JobNotice

LIMIT_REACHED = (
    "The limit of background jobs at once is reached: wait for a running job to end (or cancel "
    "it) before starting another. Nothing was started."
)
UNAVAILABLE = "Background jobs cannot be started right now. Nothing was started; try again later."
BACKGROUND_NOTE = (
    "\n\nRuns in the background: this call does not run the work. It returns a `job_id` and the "
    "status `queued` at once (unless values are missing, which are asked for first, or the "
    "limit of jobs at once is reached). Describe the work as started, not done, and never state "
    "or guess its results: they arrive in a follow-up message when the job ends. Meanwhile the "
    "user can keep asking other questions."
)
Preflight = Callable[[Mapping[str, object], RunnableConfig], tuple[object, object] | None]
Result = tuple[object, object]


def _notice(status: str, message: str) -> Result:
    return cast(JobNotice, {"status": status, "message": message}), None


def _job_input(arguments: Mapping[str, object], config: RunnableConfig) -> dict[str, object]:
    """The stored input of a job: the arguments and the user's answers to missing values."""
    configurable = cast(Mapping[str, object], config.get("configurable") or {})
    values = configurable.get("user_values")
    answers = dict(cast(Mapping[str, object], values)) if isinstance(values, dict) else None
    stored: dict[str, object] = {"arguments": dict(arguments)}
    if answers is not None:
        stored["user_values"] = answers
    return stored


async def _start(tool: BaseTool, arguments: Mapping[str, object], config: RunnableConfig) -> Result:
    """Record and queue the job, answering as the tool call must (the port is provided)."""
    port, scope = current_port(), job_scope(config)
    if port is None or scope is None:
        return _notice("unavailable", UNAVAILABLE)
    try:
        submitted = await port.submit(scope[0], scope[1], tool.name, _job_input(arguments, config))
    except JobUnavailableError:
        return _notice("unavailable", UNAVAILABLE)
    if submitted is None:
        return _notice("limit_reached", LIMIT_REACHED)
    return submitted, None


class _Submitter:
    """The calls of one submitter: run the tool here, or settle, record and queue a job."""

    def __init__(self, tool: StructuredTool, preflight: Preflight) -> None:
        if tool.func is None:
            raise TypeError(f"{tool.name} has no function to wrap")
        self._tool = tool
        self._function = tool.func
        self._preflight = preflight

    def run_here(self, arguments: Mapping[str, object], config: RunnableConfig) -> Result:
        """The tool's own call (no job system provided: the command line, evaluations)."""
        return cast(Result, self._function(**arguments, config=config))

    async def submit(self, config: RunnableConfig, **arguments: object) -> Result:
        """The async call: the tool's own result for what must be settled first, else a job."""
        if current_port() is None:
            return await asyncio.to_thread(self.run_here, arguments, config)
        early = await asyncio.to_thread(self._preflight, arguments, config)
        return early if early is not None else await _start(self._tool, arguments, config)

    def submit_sync(self, config: RunnableConfig, **arguments: object) -> Result:
        """The sync call: only without a job system (jobs are started from async code)."""
        if current_port() is not None:
            raise NotImplementedError(f"{self._tool.name} starts background jobs from async code")
        return self.run_here(arguments, config)


def heavy_submitter(tool: BaseTool, preflight: Preflight) -> BaseTool:
    """The background version of ``tool``: same name, schema and docstring, but a call queues a job.

    Args:
        tool: The registered tool (a ``StructuredTool`` whose function takes the run's config).
        preflight: Settles what must be answered before a job starts: returns the tool's own
            result for it (invalid input, missing values), or None when a job may start.
    """
    original = cast(StructuredTool, tool)
    calls = _Submitter(original, preflight)
    return StructuredTool(
        name=tool.name,
        description=f"{tool.description}{BACKGROUND_NOTE}",
        args_schema=original.args_schema,
        func=calls.submit_sync,
        coroutine=calls.submit,
        response_format="content_and_artifact",
    )
