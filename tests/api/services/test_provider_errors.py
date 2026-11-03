"""Provider failures become fixed, safe, plain-language messages."""

from __future__ import annotations

import pytest

from api.services import provider_errors as messages
from api.services.provider_errors import explain


class ProviderError(Exception):
    """Stands in for an SDK error: carries an HTTP status and the provider's error body."""

    def __init__(
        self,
        status: int,
        code: str | None = None,
        text: str = "raw provider text",
    ) -> None:
        super().__init__(text)
        self.status_code: object = status
        self.code: str | None = None
        self.body: object = {"error": {"message": text, "code": code}}


class APIConnectionError(Exception):
    """Named like the SDK's connection failure."""


class APITimeoutError(APIConnectionError):
    pass


def test_no_credits_is_said_plainly() -> None:
    assert explain(ProviderError(429, "credit_balance_exhausted")) == messages.OUT_OF_CREDITS
    assert explain(ProviderError(429, "insufficient_quota")) == messages.OUT_OF_CREDITS


def test_a_code_on_the_exception_itself_counts() -> None:
    error = ProviderError(429)
    error.body = None
    error.code = "insufficient_quota"
    assert explain(error) == messages.OUT_OF_CREDITS


def test_an_ordinary_rate_limit_is_not_called_no_credits() -> None:
    assert explain(ProviderError(429, "rate_limit_exceeded")) == messages.RATE_LIMITED
    assert explain(ProviderError(429)) == messages.RATE_LIMITED


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, messages.BAD_KEY),
        (403, messages.FORBIDDEN),
        (500, messages.PROVIDER_DOWN),
        (503, messages.PROVIDER_DOWN),
    ],
)
def test_other_statuses(status: int, message: str) -> None:
    assert explain(ProviderError(status)) == message


@pytest.mark.parametrize("error", [APIConnectionError(), APITimeoutError()])
def test_network_failures(error: Exception) -> None:
    assert explain(error) == messages.UNREACHABLE


@pytest.mark.parametrize(
    "error",
    [RuntimeError("x"), ValueError("y"), ProviderError(400), ProviderError(404), KeyError("z")],
)
def test_anything_else_is_not_explained(error: Exception) -> None:
    assert explain(error) is None


def test_a_status_that_is_not_a_number_is_ignored() -> None:
    error = ProviderError(429, "insufficient_quota")
    error.status_code = True
    assert explain(error) is None


def test_the_providers_own_text_is_never_part_of_a_message() -> None:
    secret = "sk-proj-" + "Zz9" * 10  # pragma: allowlist secret
    shown = explain(ProviderError(401, text=f"Incorrect API key provided: {secret}"))
    assert shown is not None and secret not in shown and "Incorrect" not in shown


def test_a_malformed_body_does_not_break_it() -> None:
    error = ProviderError(429)
    error.body = ["not", "a", "mapping"]
    assert explain(error) == messages.RATE_LIMITED
    error.body = {"error": "just text"}
    assert explain(error) == messages.RATE_LIMITED
