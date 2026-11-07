"""Tests for the log redaction filter (``app.redaction``)."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from app.redaction import (
    LITERAL_REDACTED,
    REDACTED,
    SecretRedactionFilter,
    install_redaction,
    protect_secrets,
    redact,
)

KEY = "sk-proj-" + "a1B2c3D4e5" * 3  # pragma: allowlist secret


@pytest.fixture
def captured() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    logger = logging.getLogger("tests.redaction")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield logger, stream
    logger.removeHandler(handler)


def test_key_in_message(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    logger.info(f"calling with {KEY}")
    assert KEY not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_key_in_arguments(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    logger.info("auth %s", KEY)
    logger.info("auth %(key)s", {"key": KEY})
    assert KEY not in stream.getvalue()
    assert stream.getvalue().count(REDACTED) == 2


def test_key_in_exception(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    try:
        raise RuntimeError(f"provider rejected {KEY}")
    except RuntimeError:
        logger.exception("failed")
    output = stream.getvalue()
    assert "Traceback" in output
    assert KEY not in output
    assert REDACTED in output


def test_key_in_exception_argument(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    logger.warning("error: %s", ValueError(f"bad {KEY}"))
    assert KEY not in stream.getvalue()


def test_short_sk_strings_untouched(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    logger.info("sk-abc and task-123")
    assert stream.getvalue().strip() == "sk-abc and task-123"


def test_filter_never_drops_records() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, KEY, None, None)
    assert SecretRedactionFilter().filter(record) is True
    assert record.getMessage() == REDACTED


def test_redact_replaces_every_key() -> None:
    assert redact(f"{KEY} and {KEY}") == f"{REDACTED} and {REDACTED}"


def test_install_covers_named_loggers_and_their_handlers() -> None:
    logger = logging.getLogger("tests.install")
    handler = logging.StreamHandler(io.StringIO())
    logger.addHandler(handler)
    try:
        install_redaction(["tests.install"])
        install_redaction(["tests.install"])
        filters = [f for f in logger.filters if isinstance(f, SecretRedactionFilter)]
        assert len(filters) == 1
        assert any(isinstance(f, SecretRedactionFilter) for f in handler.filters)
    finally:
        logger.removeHandler(handler)
        logger.filters.clear()


def test_access_log_still_formats(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", f"/x?k={KEY}", "1.1", 200)
    assert '"GET /x?k=' + REDACTED + ' HTTP/1.1" 200' in stream.getvalue()


# --- values with no recognisable shape (the Census and CompTox keys) --------------------------

SHAPELESS = "c3n5u5k3y" + "7f" * 16  # pragma: allowlist secret


def test_a_protected_value_is_redacted_everywhere_in_a_record(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    with protect_secrets([SHAPELESS]):
        logger.info(f"in the message {SHAPELESS}")
        logger.info("in an argument %s", SHAPELESS)
        try:
            raise RuntimeError(f"in an exception {SHAPELESS}")
        except RuntimeError:
            logger.exception("failed")
    assert SHAPELESS not in stream.getvalue()
    assert stream.getvalue().count(LITERAL_REDACTED) == 3


def test_protection_ends_with_the_block(captured: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = captured
    with protect_secrets([SHAPELESS]):
        pass
    logger.info(f"after {SHAPELESS}")
    assert SHAPELESS in stream.getvalue()


def test_overlapping_turns_do_not_unprotect_each_other(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    with protect_secrets([SHAPELESS]):
        with protect_secrets([SHAPELESS]):
            pass
        logger.info(f"still {SHAPELESS}")
    assert SHAPELESS not in stream.getvalue()


def test_short_values_are_not_protected_so_ordinary_text_survives(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    with protect_secrets(["abc", ""]):
        logger.info("abc is an ordinary string")
    assert stream.getvalue().strip() == "abc is an ordinary string"


def test_the_longest_value_wins_when_one_contains_another(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    with protect_secrets([SHAPELESS, SHAPELESS[:12]]):
        logger.info(f"value {SHAPELESS}")
    assert SHAPELESS[12:] not in stream.getvalue()


# --- shapes the sk- pattern alone misses -----------------------------------------------------

MASKED = "sk-proj-" + "*" * 32 + "p8UA"  # how the provider echoes a rejected key back


def test_a_masked_key_echoed_by_the_provider_loses_its_visible_end(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    logger.warning(
        "Error code: 401 - Incorrect API key provided: %s. You can find your key",
        MASKED,
    )
    assert "p8UA" not in stream.getvalue() and "****" not in stream.getvalue()
    assert REDACTED in stream.getvalue()


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer abcdefghijklmnop1234",
        "{'Authorization': 'Bearer abcdefghijklmnop1234'}",
        "api_key='abcdefghijk123'",  # pragma: allowlist secret
        "x-api-key: abcdefghijk123",  # pragma: allowlist secret
        "api-key=abcdefghijk123",  # pragma: allowlist secret
        "access_token: abcdefghijk123",
        "password=hunter22222",  # pragma: allowlist secret
    ],
)
def test_bearer_tokens_and_key_assignments_of_any_shape_lose_their_value(text: str) -> None:
    shown = redact(text)
    assert "abcdefghijk" not in shown and "hunter22222" not in shown
    assert LITERAL_REDACTED in shown


def test_a_bearer_key_is_redacted_once_and_cleanly() -> None:
    assert redact(f"Authorization: Bearer {KEY}") == f"Authorization: Bearer {LITERAL_REDACTED}"


@pytest.mark.parametrize(
    "text",
    [
        "max_tokens=100000000 api_key_env_var=OPENAI_API_KEY",
        "turn failed (578ac54e8d50): OpenAIRateLimitError",
        "OPENAI_API_KEY is not set",
        "password reset not requested",
        "a secret garden",
    ],
)
def test_ordinary_text_about_keys_is_left_alone(text: str) -> None:
    assert redact(text) == text


def test_a_non_string_message_with_a_bearer_token_is_redacted(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured

    class Message:
        def __str__(self) -> str:
            return "Authorization: Bearer abcdefghijklmnop1234"

    logger.warning(Message())  # type: ignore[arg-type]
    assert "abcdefghijk" not in stream.getvalue()


def test_redacting_twice_changes_nothing_more() -> None:
    once = redact(f"bad key {KEY} and {MASKED} and Bearer abcdefghijklmnop1234")
    assert redact(once) == once


# --- a key in a URL, and keys from the environment ---------------------------------------------

CENSUS = "c3n5u5k3y" + "7f" * 16  # pragma: allowlist secret
CENSUS_URL = (
    "HTTP Request: GET https://api.census.gov/data/2023/acs/acs5?get=B01001_001E"
    f'&for=tract:*&in=state:48&key={CENSUS} "HTTP/1.1 200 OK"'
)


def test_a_key_in_a_url_query_string_is_redacted_whatever_its_shape() -> None:
    shown = redact(CENSUS_URL)
    assert CENSUS not in shown
    assert "key=" + LITERAL_REDACTED in shown
    assert "for=tract:*&in=state:48" in shown  # the rest of the URL stays readable


@pytest.mark.parametrize("name", ["key", "api_key", "apikey", "access_token", "token"])
def test_each_query_parameter_name_is_covered(name: str) -> None:
    assert "abcdefghijk" not in redact(f"GET https://x.test/p?a=1&{name}=abcdefghijk&b=2")


def test_the_httpx_logger_does_not_show_a_census_key(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    logger.info('HTTP Request: GET %s "HTTP/1.1 200 OK"', f"https://api.census.gov/x?key={CENSUS}")
    assert CENSUS not in stream.getvalue()


DATABASE_URL = "postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate"  # pragma: allowlist secret


def test_a_database_password_never_reaches_a_log_line() -> None:
    line = redact(f"connect failed: {DATABASE_URL}")
    assert "s3cr3t" not in line
    assert "postgresql+psycopg://ecofate:" in line
    assert "@db:5432/ecofate" in line
    assert redact(line) == line  # redacting twice is harmless
