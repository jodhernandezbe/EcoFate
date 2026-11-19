"""``check_job_status``: how the thread's background jobs are going."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from tools.jobs.port import current_port, job_scope
from tools.schemas import JobStatusResult

NO_JOBS = "No background job was found for this conversation."
UNAVAILABLE = "Background jobs are not available in this session."
NOTE = (
    "A queued or running job has been started, not finished: describe it as in progress and "
    "never state its results. Its results come in a follow-up message when it ends."
)


@tool
async def check_job_status(job_id: str | None = None, *, config: RunnableConfig) -> JobStatusResult:
    """Report how this conversation's background jobs are going.

    Purpose:
        Use this when the user asks how a long task (such as an assessment that was started in
        the background) is going, or when you need to know whether it has ended. It never
        starts or changes a job. A job that is `queued` or `running` has been started, not
        finished: say so, give its queue position and elapsed time, never state or guess its
        results, and offer to keep answering other questions meanwhile. When it ends, its results
        arrive in a follow-up message; do not describe them before then.

    Args:
        job_id: The job's id, as returned when it was started; omit to list every job of this
            conversation.

    Returns:
        A dict with `jobs` (each with job_id, tool, status: queued, running, succeeded, failed,
        cancelled or interrupted; position: jobs queued ahead of it, only while queued;
        elapsed_seconds: seconds waiting while queued, running while running, or the time it
        took once ended; outcome: a short fixed description, only once ended) and a `note`.
    """
    port, scope = current_port(), job_scope(config)
    if port is None or scope is None:
        return JobStatusResult(jobs=[], note=UNAVAILABLE)
    found = await port.status(scope[0], scope[1], job_id)
    return JobStatusResult(jobs=found, note=NOTE if found else NO_JOBS)
