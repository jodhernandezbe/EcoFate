"""Provider failures become fixed, safe, plain-language messages."""

from __future__ import annotations

import pytest

from api.services import provider_errors as messages
from api.services.provider_errors import explain, interruption_message, message_for
from app.turns import FailureReason


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
    assert explain(error) == messages.PROVIDER_DOWN  # unreachable is a provider failure too


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


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        (FailureReason.OUT_OF_CREDITS, messages.OUT_OF_CREDITS),
        (FailureReason.RATE_LIMITED, messages.RATE_LIMITED),
        (FailureReason.BAD_KEY, messages.BAD_KEY),
        (FailureReason.PROVIDER_DOWN, messages.PROVIDER_DOWN),
        (FailureReason.STEP_LIMIT, messages.STEP_LIMIT),
        (FailureReason.WORKER_LOST, messages.WORKER_LOST),
    ],
)
def test_each_interruption_says_what_to_do_before_resuming(
    reason: FailureReason,
    message: str,
) -> None:
    assert interruption_message(reason, resumable=True) == message
    assert "Resume" in message


def test_an_interruption_that_cannot_be_resumed_says_to_send_a_new_message() -> None:
    message = interruption_message(FailureReason.OUT_OF_CREDITS, resumable=False)
    assert message == messages.NOT_RESUMABLE
    assert "Resume" not in message.replace("resumed", "")


def test_the_step_limit_is_not_a_provider_failure() -> None:
    assert message_for(FailureReason.STEP_LIMIT) == messages.STEP_LIMIT
    assert message_for(FailureReason.UNEXPECTED) == messages.GENERIC_ERROR
