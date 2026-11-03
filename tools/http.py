"""Throttled, retrying JSON GET shared by the tools that call an outside service."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpRequestError(RuntimeError):
    """A request could not be completed; no partial result should be used.

    Attributes:
        status_code: HTTP status of the last answer, or None if there was none (a timeout or
            a connection failure).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Create the error with its message and, if known, the last HTTP status."""
        super().__init__(message)
        self.status_code = status_code


class RetryPolicy(Protocol):
    """How politely a service is called (any settings object with these four values)."""

    @property
    def delay_seconds(self) -> float:
        """Wait before each request, in seconds."""
        ...

    @property
    def timeout_seconds(self) -> float:
        """Per-request timeout, in seconds."""
        ...

    @property
    def max_retries(self) -> int:
        """Retries after a throttled, failed or timed-out request."""
        ...

    @property
    def backoff_seconds(self) -> float:
        """First retry wait in seconds; doubles on each further retry."""
        ...


@dataclass(frozen=True)
class _Retry:
    """A failed attempt worth repeating, with the server's requested wait if it gave one."""

    reason: str
    wait: float | None = None
    status: int | None = None


def retry_after(response: httpx.Response) -> float | None:
    """Return the ``Retry-After`` header as seconds if it is a non-negative number."""
    raw = response.headers.get("Retry-After", "").strip()
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class RetryingClient:
    """Fetches JSON one request at a time, politely.

    Every request waits the configured delay first. Throttling (HTTP 429), server errors,
    timeouts and malformed JSON are retried a configured number of times with a doubling wait
    (``Retry-After`` is honoured, up to the request timeout); any other non-200 answer fails.
    """

    def __init__(
        self,
        policy: RetryPolicy,
        client: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a client.

        Args:
            policy: Delay, timeout and retry values.
            client: HTTP client (injectable for tests).
            sleep: Function used to wait; replaced in tests.
        """
        self._policy = policy
        self._client = client
        self._sleep = sleep

    def get_json(self, url: str, params: Mapping[str, str | int | float] | None = None) -> object:
        """Return the decoded JSON body of a GET request.

        Args:
            url: Full URL.
            params: Query parameters, if any.

        Raises:
            HttpRequestError: If the request still fails after the configured retries, or
                the answer is a non-retryable error status.
        """
        retries = self._policy.max_retries
        reason = ""
        status: int | None = None
        for attempt in range(retries + 1):
            self._sleep(self._policy.delay_seconds)
            outcome = self._attempt(url, params)
            if not isinstance(outcome, _Retry):
                return outcome.payload
            reason, status = outcome.reason, outcome.status
            logger.debug("request failed (%s), attempt %d", reason, attempt + 1)
            if attempt < retries:
                self._sleep(self._wait(attempt, outcome))
        raise HttpRequestError(f"request failed after {retries + 1} attempts: {reason}", status)

    def _wait(self, attempt: int, retry: _Retry) -> float:
        backoff = self._policy.backoff_seconds * 2**attempt
        if retry.wait is None:
            return backoff
        return min(retry.wait, self._policy.timeout_seconds)

    def _attempt(self, url: str, params: Mapping[str, str | int | float] | None) -> _Body | _Retry:
        try:
            response = self._client.get(url, params=params, timeout=self._policy.timeout_seconds)
        except httpx.HTTPError as exc:
            return _Retry(f"{type(exc).__name__}")
        return _outcome(response)


def _outcome(response: httpx.Response) -> _Body | _Retry:
    """Read one answer: a decoded body, a reason to retry, or an error for a final status."""
    if response.status_code in RETRYABLE_STATUS:
        return _Retry(
            f"HTTP {response.status_code}",
            retry_after(response),
            response.status_code,
        )
    if response.status_code != 200:
        raise HttpRequestError(
            f"server returned HTTP {response.status_code}",
            response.status_code,
        )
    try:
        return _Body(cast(object, response.json()))
    except ValueError:
        return _Retry("malformed JSON")


@dataclass(frozen=True)
class _Body:
    """A decoded JSON answer (a wrapper so a JSON null is not mistaken for a failure)."""

    payload: object
