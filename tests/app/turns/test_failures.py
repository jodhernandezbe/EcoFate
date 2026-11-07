"""A failed turn is classified as one reason code; the error's text never matters."""

from __future__ import annotations

import pytest

from app.turns.failures import FailureReason, KeysUnavailableError, classify, new_correlation_id


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
        (APIConnectionError(), FailureReason.UNREACHABLE),
        (APITimeoutError(), FailureReason.UNREACHABLE),
        (ConnectTimeout(), FailureReason.UNREACHABLE),
        (KeysUnavailableError(FailureReason.NO_KEY), FailureReason.NO_KEY),
        (
            KeysUnavailableError(FailureReason.KEYCHAIN_UNAVAILABLE),
            FailureReason.KEYCHAIN_UNAVAILABLE,
        ),
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
