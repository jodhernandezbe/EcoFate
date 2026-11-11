"""A failed turn is classified as one reason code; the error's text never matters."""

from __future__ import annotations

import pytest
from langgraph.errors import GraphRecursionError

from app.turns.failures import (
    RESUMABLE_REASONS,
    FailureReason,
    KeysUnavailableError,
    StopRequestedError,
    classify,
    new_correlation_id,
    resumable,
)


class ProviderError(Exception):
    """Stands in for an SDK error: an HTTP status and the provider's error body."""

    def __init__(self, status: object, code: str | None = None, body: object = None) -> None:
        super().__init__("raw provider text")
        self.status_code = status
        self.code: str | None = None
        self.body = body if body is not None else {"error": {"code": code}}


class APIConnectionError(Exception):
    """Named like the SDK's connection failure."""


class APITimeoutError(APIConnectionError):
    """A subclass is recognised through its bases."""


class ConnectTimeout(Exception):
    """Named like the HTTP client's timeout."""


class SoftTimeLimitExceeded(Exception):
    """Named like the task queue's soft time limit."""


class TimeLimitNamedLike(Exception):
    """A name that only contains the limit's name is not it."""


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ProviderError(429, "insufficient_quota"), FailureReason.OUT_OF_CREDITS),
        (ProviderError(429, "credit_balance_exhausted"), FailureReason.OUT_OF_CREDITS),
        (ProviderError(429, "rate_limit_exceeded"), FailureReason.RATE_LIMITED),
        (ProviderError(429), FailureReason.RATE_LIMITED),
        (ProviderError(401), FailureReason.BAD_KEY),
        (ProviderError(403), FailureReason.FORBIDDEN),
        (ProviderError(500), FailureReason.PROVIDER_DOWN),
        (ProviderError(503), FailureReason.PROVIDER_DOWN),
        (APIConnectionError(), FailureReason.PROVIDER_DOWN),
        (APITimeoutError(), FailureReason.PROVIDER_DOWN),
        (ConnectTimeout(), FailureReason.PROVIDER_DOWN),
        (KeysUnavailableError(FailureReason.NO_KEY), FailureReason.NO_KEY),
        (
            KeysUnavailableError(FailureReason.KEYCHAIN_UNAVAILABLE),
            FailureReason.KEYCHAIN_UNAVAILABLE,
        ),
        (GraphRecursionError("Recursion limit of 80 reached"), FailureReason.STEP_LIMIT),
        (StopRequestedError(FailureReason.CANCELLED), FailureReason.CANCELLED),
        (StopRequestedError(FailureReason.TIME_LIMIT), FailureReason.TIME_LIMIT),
        (SoftTimeLimitExceeded(), FailureReason.TIME_LIMIT),
        (TimeLimitNamedLike("SoftTimeLimitExceeded"), FailureReason.UNEXPECTED),
        (RuntimeError("boom"), FailureReason.UNEXPECTED),
        (ProviderError(400), FailureReason.UNEXPECTED),
        (ProviderError(404), FailureReason.UNEXPECTED),
    ],
)
def test_each_failure_has_its_reason(error: Exception, reason: FailureReason) -> None:
    assert classify(error) == reason


@pytest.mark.parametrize("status", [True, False, "429", 429.0, None])
def test_a_status_that_is_not_an_integer_is_ignored(status: object) -> None:
    assert classify(ProviderError(status, "insufficient_quota")) == FailureReason.UNEXPECTED


@pytest.mark.parametrize(
    "body",
    [["not", "a", "mapping"], {"error": "just text"}, {"error": {"code": 42}}, "text"],
)
def test_a_body_of_the_wrong_shape_is_no_credit_code(body: object) -> None:
    assert classify(ProviderError(429, body=body)) == FailureReason.RATE_LIMITED


def test_a_code_on_the_exception_itself_counts() -> None:
    error = ProviderError(429, body={})
    error.code = "insufficient_quota"
    assert classify(error) == FailureReason.OUT_OF_CREDITS


def test_correlation_ids_are_short_and_distinct() -> None:
    first, second = new_correlation_id(), new_correlation_id()
    assert len(first) == 12 and first != second


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (FailureReason.OUT_OF_CREDITS, True),
        (FailureReason.RATE_LIMITED, True),
        (FailureReason.BAD_KEY, True),
        (FailureReason.PROVIDER_DOWN, True),
        (FailureReason.STEP_LIMIT, True),
        (FailureReason.WORKER_LOST, True),
        (FailureReason.CANCELLED, True),
        (FailureReason.TIME_LIMIT, True),
        (FailureReason.FORBIDDEN, False),
        (FailureReason.UNEXPECTED, False),
        (FailureReason.SUPERSEDED, False),
        (FailureReason.NO_KEY, False),
        (FailureReason.KEYCHAIN_UNAVAILABLE, False),
    ],
)
def test_only_fixable_reasons_are_resumable(reason: FailureReason, expected: bool) -> None:
    assert resumable(reason) is expected


def test_an_unknown_exception_is_unexpected_and_not_resumable() -> None:
    class SomethingNew(Exception):
        """No status, no code, no known name."""

    reason = classify(SomethingNew("429 insufficient_quota rate limit"))  # text never counts
    assert reason == FailureReason.UNEXPECTED
    assert not resumable(reason)
    assert reason not in RESUMABLE_REASONS
