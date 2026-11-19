"""The stored input of an ``assess_facilities`` job, checked (it was read from the database).

Shape: ``{"arguments": {the tool's arguments}, "user_values": {"supplied": {...}, "declined":
[...]}}``; ``user_values`` (the user's answers to missing values, read by the chemical lookup
from the run's configuration) is optional. Anything that does not fit raises
``InvalidJobInputError``; nothing is coerced, and a number is finite and never a ``bool``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from langchain_core.runnables import RunnableConfig

from tools.schemas import InvalidJobInputError, Toxicity

_ARGUMENTS = frozenset({"cas_number", "frs_ids", "state", "city", "radius_km", "toxicity"})


@dataclass(frozen=True)
class AssessmentRequest:
    """The checked arguments of one assessment job."""

    cas_number: str
    frs_ids: list[str] | None
    place: tuple[str | None, str | None]
    radius_km: float | None
    toxicity: Toxicity | None
    config: RunnableConfig


def _mapping(value: object, what: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) for k in cast(dict[object, object], value)
    ):
        raise InvalidJobInputError(f"{what} must be an object")
    return cast(Mapping[str, object], value)


def _text(value: object, what: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidJobInputError(f"{what} must be a non-empty string")
    return value


def _number(value: object, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidJobInputError(f"{what} must be a finite number")
    return float(value)


def _ids(value: object) -> list[str] | None:
    if value is None:
        return None
    items = cast(list[object], value) if isinstance(value, list) else None
    if items is None or not all(isinstance(i, str) and i.strip() for i in items):
        raise InvalidJobInputError("frs_ids must be a list of non-empty strings")
    return [str(i) for i in items]


def _toxicity(value: object) -> Toxicity | None:
    if value is None:
        return None
    given = _mapping(value, "toxicity")
    if not set(given) <= {"rfc", "iur"}:
        raise InvalidJobInputError("toxicity holds only rfc and iur")
    return Toxicity(rfc=_number(given.get("rfc"), "rfc"), iur=_number(given.get("iur"), "iur"))


def _config(raw: object) -> RunnableConfig:
    """The run configuration that carries the user's answers to the chemical lookup."""
    if raw is None:
        return {}
    values = _mapping(raw, "user_values")
    return {"configurable": {"user_values": dict(values)}}


def parse_job_input(stored: Mapping[str, object]) -> AssessmentRequest:
    """The request an ``assess_facilities`` job's stored input describes.

    Raises:
        InvalidJobInputError: The input does not fit (an unknown argument, a wrong type, a
            missing CAS number, a non-finite number).
    """
    arguments = _mapping(stored.get("arguments"), "arguments")
    if not set(arguments) <= _ARGUMENTS:
        raise InvalidJobInputError("arguments hold a name the tool does not take")
    return AssessmentRequest(
        cas_number=cast(str, _text(arguments.get("cas_number"), "cas_number", required=True)),
        frs_ids=_ids(arguments.get("frs_ids")),
        place=(_text(arguments.get("state"), "state"), _text(arguments.get("city"), "city")),
        radius_km=_number(arguments.get("radius_km"), "radius_km"),
        toxicity=_toxicity(arguments.get("toxicity")),
        config=_config(stored.get("user_values")),
    )
