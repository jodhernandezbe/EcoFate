"""The tools a background job may run, as the worker's job runner needs them (by tool name).

``agent`` reads tools only through ``tools.registry``; the worker and ``app`` do not import
tools, so this is how the job runner receives its tool runners (injected, never looked up).
"""

from __future__ import annotations

from collections.abc import Mapping

from tools.registry import get_job_runners
from tools.schemas import JobRunner


def job_runners() -> Mapping[str, JobRunner]:
    """The runner of each tool that can run as a background job, by tool name."""
    return get_job_runners()
