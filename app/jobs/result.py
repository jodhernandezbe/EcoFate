"""A tool's result made storable: strict JSON data, with the same redaction as tool results.

The result is copied as data (non-finite numbers become absent), then every string passes
``app.redaction.redact`` so a key-shaped or protected value never reaches the database.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from app.redaction import redact
from commons.json_safe import json_safe
from storage.job_model import JsonObject
from tools.schemas import JobResult


def _scrub(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in cast(dict[str, object], value).items()}
    if isinstance(value, list):
        return [_scrub(item) for item in cast(list[object], value)]
    return value


def _object(value: Mapping[str, object]) -> JsonObject:
    data = json_safe(value)
    if not isinstance(data, dict):
        raise TypeError("a job result part must be an object")
    return cast(JsonObject, _scrub(cast(dict[str, object], data)))


def storable(result: JobResult) -> tuple[JsonObject, JsonObject]:
    """The ``(content, artifact)`` of a tool's result as redacted JSON objects.

    Raises:
        TypeError: A part is not JSON data (the job then fails with ``invalid_result``).
    """
    content, artifact = result
    return _object(content), _object(artifact)
