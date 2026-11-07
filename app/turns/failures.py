"""Classify why a turn failed, as one reason code from a closed set (never the error's text).

The provider package is not imported: a provider failure is recognised by what it carries (an
HTTP ``status_code`` and an error ``code``) and by the names of its classes. Each front end maps
a reason to its own fixed message.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from enum import StrEnum
from typing import cast

from langgraph.errors import GraphRecursionError


class FailureReason(StrEnum):
    """Why a turn stopped before its answer."""

    NO_KEY = "no_key"
    KEYCHAIN_UNAVAILABLE = "keychain_unavailable"
    OUT_OF_CREDITS = "out_of_credits"
    RATE_LIMITED = "rate_limited"
    BAD_KEY = "bad_key"
    FORBIDDEN = "forbidden"
    PROVIDER_DOWN = "provider_down"  # the provider failed on its side or could not be reached
    STEP_LIMIT = "step_limit"
    WORKER_LOST = "worker_lost"  # the process running the turn stopped (never classified)
    SUPERSEDED = "superseded"  # a new message abandoned the interrupted turn (never classified)
    UNEXPECTED = "unexpected"


# Reasons the user can act on before the turn started (no key); nothing worth logging.
SETUP_REASONS = frozenset({FailureReason.NO_KEY, FailureReason.KEYCHAIN_UNAVAILABLE})
# Reasons the user can fix (or that a stopped process caused) after which the turn continues
# from its last checkpoint. Anything else (``forbidden``, an unexpected bug) fails the turn.
RESUMABLE_REASONS = frozenset(
    {
        FailureReason.OUT_OF_CREDITS,
        FailureReason.RATE_LIMITED,
        FailureReason.BAD_KEY,
        FailureReason.PROVIDER_DOWN,
        FailureReason.STEP_LIMIT,
        FailureReason.WORKER_LOST,
    },
)


def resumable(reason: FailureReason) -> bool:
    """Whether a turn stopped for ``reason`` is interrupted (resumable) rather than failed."""
    return reason in RESUMABLE_REASONS


class KeysUnavailableError(Exception):
    """The turn's keys could not be read; ``reason`` says why."""

    def __init__(self, reason: FailureReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


_NO_CREDIT_CODES = frozenset({"insufficient_quota", "credit_balance_exhausted"})
_NETWORK_FAILURES = frozenset({"APIConnectionError", "APITimeoutError", "ConnectTimeout"})
_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN, _HTTP_RATE_LIMITED, _HTTP_SERVER_ERROR = 401, 403, 429, 500


def new_correlation_id() -> str:
    """A short random id that ties a user-visible error to its log entry."""
    return uuid.uuid4().hex[:12]


def _codes(exc: BaseException) -> set[str]:
    """The error codes the failure carries, as the provider's SDK exposes them."""
    found = {getattr(exc, "code", None)}
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        outer = cast(Mapping[str, object], body)
        error = outer.get("error", outer)
        if isinstance(error, dict):
            found.add(cast(Mapping[str, object], error).get("code"))
    return {code for code in found if isinstance(code, str)}


def _status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _by_status(exc: BaseException, status: int) -> FailureReason | None:
    if status == _HTTP_RATE_LIMITED:
        no_credit = _codes(exc) & _NO_CREDIT_CODES
        return FailureReason.OUT_OF_CREDITS if no_credit else FailureReason.RATE_LIMITED
    if status == _HTTP_UNAUTHORIZED:
        return FailureReason.BAD_KEY
    if status == _HTTP_FORBIDDEN:
        return FailureReason.FORBIDDEN
    if status >= _HTTP_SERVER_ERROR:
        return FailureReason.PROVIDER_DOWN
    return None


def classify(exc: BaseException) -> FailureReason:
    """The reason a turn failed with ``exc``; ``unexpected`` when it is no known failure."""
    if isinstance(exc, KeysUnavailableError):
        return exc.reason
    if isinstance(exc, GraphRecursionError):
        return FailureReason.STEP_LIMIT
    status = _status(exc)
    reason = _by_status(exc, status) if status is not None else None
    if reason is not None:
        return reason
    if any(cls.__name__ in _NETWORK_FAILURES for cls in type(exc).__mro__):
        return FailureReason.PROVIDER_DOWN
    return FailureReason.UNEXPECTED
