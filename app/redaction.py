"""Log redaction: scrub key-shaped strings and protected values before a handler emits them.

Shared by every front end of the program (the web API today, a background worker later); it
holds no HTTP knowledge.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager

from commons.key_patterns import (
    ASSIGNMENT_PATTERN,
    BEARER_PATTERN,
    DATABASE_URL_PATTERN,
    MASKED_KEY_PATTERN,
    QUERY_PATTERN,
    SECRET_PATTERN,
)

REDACTED = "sk-***REDACTED***"
# Loggers whose records (and handlers) get the filter: the root, the server and the HTTP client.
REDACTED_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore")
_PLAIN = (int, float, bool, type(None))
_FORMATTER = logging.Formatter()


LITERAL_REDACTED = "***REDACTED***"
MIN_LITERAL_LENGTH = 8  # shorter values would mangle ordinary log text
_LITERALS: Counter[str] = Counter()
_LITERALS_LOCK = threading.Lock()


@contextmanager
def protect_secrets(values: Iterable[str]) -> Generator[None]:
    """Redact these exact values, wherever they appear in a log record, until the block exits.

    For keys with no recognisable shape (Census, CompTox). Counted, so concurrent turns that
    share a value do not unprotect each other.
    """
    items = [value for value in values if len(value) >= MIN_LITERAL_LENGTH]
    with _LITERALS_LOCK:
        _LITERALS.update(items)
    try:
        yield
    finally:
        with _LITERALS_LOCK:
            _LITERALS.subtract(items)
            for value in [v for v, count in _LITERALS.items() if count <= 0]:
                del _LITERALS[value]


def redact(text: str) -> str:
    """Return ``text`` with key-shaped substrings and protected values replaced."""
    text = DATABASE_URL_PATTERN.sub(rf"\1{LITERAL_REDACTED}\3", text)
    text = BEARER_PATTERN.sub(rf"\1{LITERAL_REDACTED}", text)
    text = QUERY_PATTERN.sub(rf"\1{LITERAL_REDACTED}", text)
    text = ASSIGNMENT_PATTERN.sub(rf"\1\2{LITERAL_REDACTED}", text)
    text = SECRET_PATTERN.sub(REDACTED, MASKED_KEY_PATTERN.sub(REDACTED, text))
    with _LITERALS_LOCK:
        literals = sorted(_LITERALS, key=len, reverse=True)
    for value in literals:
        text = text.replace(value, LITERAL_REDACTED)
    return text


def _redact_arg(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, _PLAIN):
        return value
    text = str(value)
    return redact(text) if redact(text) != text else value


LogArgs = tuple[object, ...] | Mapping[str, object]


def _redact_args(args: LogArgs) -> LogArgs:
    if isinstance(args, tuple):
        return tuple(_redact_arg(value) for value in args)
    return {key: _redact_arg(value) for key, value in args.items()}


class SecretRedactionFilter(logging.Filter):
    """Redact key-shaped strings in a record's message, arguments, exception and stack.

    Arguments are redacted one by one (not collapsed into the message) so formatters that read
    ``record.args``, such as the server's access log, keep working. The exception traceback is
    rendered once, redacted into ``exc_text``, and ``exc_info`` dropped so no handler can
    re-render the raw text. Never drops a record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        elif redact(str(record.msg)) != str(record.msg):
            record.msg = redact(str(record.msg))
        if record.args:
            record.args = _redact_args(record.args)
        if record.exc_info:
            record.exc_text = redact(_FORMATTER.formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def _attach(target: logging.Logger | logging.Handler, flt: SecretRedactionFilter) -> None:
    if not any(isinstance(existing, SecretRedactionFilter) for existing in target.filters):
        target.addFilter(flt)


def install_redaction(names: Iterable[str] = REDACTED_LOGGERS) -> None:
    """Attach the filter to each named logger and to all of their handlers (idempotent).

    Logger filters do not see records propagated from child loggers, so the handlers get
    the filter too.
    """
    flt = SecretRedactionFilter()
    for name in names:
        logger = logging.getLogger(name)
        _attach(logger, flt)
        for handler in logger.handlers:
            _attach(handler, flt)
