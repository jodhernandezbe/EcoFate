"""Rows of ``jobs`` to ``Job``: stored rows are untrusted, so shape and type are checked.

A row whose status is unknown, whose reason does not fit its status or whose JSON is not an
object is absent and logged with its thread id (never its content); nothing is coerced.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from storage.job_model import REASONED_STATUSES, Job, JobStatus, JsonObject

logger = logging.getLogger(__name__)


def _status(value: object) -> JobStatus | None:
    try:
        return JobStatus(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _object(value: object, *, required: bool) -> tuple[bool, JsonObject | None]:
    """Whether ``value`` is acceptable as a JSON object column, and the object."""
    if value is None:
        return (not required), None
    if isinstance(value, dict):
        return True, cast(JsonObject, value)
    return False, None


def _fits(row: Mapping[str, object], status: JobStatus | None) -> bool:
    """Whether the reason and the three JSON columns suit the status."""
    reason = row.get("failure_reason")
    if status is None or not (reason is None or isinstance(reason, str)):
        return False
    if (reason is None) == (status in REASONED_STATUSES):
        return False
    results = [_object(row.get(name), required=False)[0] for name in _RESULTS]
    return _object(row.get("input"), required=True)[0] and all(results)


_RESULTS = ("result_content", "result_artifact")


def job_from_row(row: Mapping[str, object]) -> Job | None:
    """A stored job, or None (with a warning) when its row does not fit."""
    status, owner = _status(row.get("status")), row.get("owner_id")
    if not isinstance(owner, UUID) or not _fits(row, status) or status is None:
        logger.warning(
            "Ignoring a stored job that does not decode (thread %s)",
            row.get("thread_id"),
        )
        return None
    return _job(row, owner, status)


def _job(row: Mapping[str, object], owner: UUID, status: JobStatus) -> Job:
    """The job of a row already checked by ``_fits``."""
    return Job(
        id=str(row["id"]),
        owner_id=owner,
        thread_id=str(row["thread_id"]),
        tool=str(row["tool"]),
        input=cast(JsonObject, row["input"]),
        status=status,
        queued_at=cast(datetime, row["queued_at"]),
        started_at=cast(datetime | None, row.get("started_at")),
        ended_at=cast(datetime | None, row.get("ended_at")),
        heartbeat_at=cast(datetime | None, row.get("heartbeat_at")),
        cancel_requested=row.get("cancel_requested") is True,
        result_content=_object(row.get("result_content"), required=False)[1],
        result_artifact=_object(row.get("result_artifact"), required=False)[1],
        failure_reason=cast(str | None, row.get("failure_reason")),
    )
