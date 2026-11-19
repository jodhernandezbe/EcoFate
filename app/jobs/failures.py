"""Why a background job did not succeed: one fixed reason code, never an exception's text."""

from __future__ import annotations

from enum import StrEnum


class JobFailure(StrEnum):
    """The reason stored with a job that ended ``failed``, ``cancelled`` or ``interrupted``."""

    CANCELLED = "cancelled"  # the user stopped the job between two steps of the tool
    TIME_LIMIT = "time_limit"  # the job ran past the tools pool's soft or hard limit
    WORKER_LOST = "worker_lost"  # the process running the job stopped (never classified here)
    NOT_STARTED = "not_started"  # no worker took the job (its task message was lost)
    BAD_INPUT = "bad_input"  # the stored input does not fit the tool
    UNKNOWN_TOOL = "unknown_tool"  # the job names a tool no runner exists for
    INVALID_RESULT = "invalid_result"  # the tool's result is not storable data
    UNEXPECTED = "unexpected"  # anything else (the log has it under a correlation id)
