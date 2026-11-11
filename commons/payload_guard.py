"""Refuse a message bound for another process if it carries anything that looks like a secret.

Work handed to a queue holds identifiers only (user, thread, turn). ``assert_ids_only`` is the
check run before a payload is enqueued: it walks the JSON-able payload and raises on a
credential-named field, a key-shaped string, or the exact value of a protected secret. Pure:
the protected values come in as an argument.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from commons.key_patterns import KEY_PATTERNS

DENIED_FIELD_WORDS = ("api_key", "apikey", "password", "token", "secret", "cookie", "credential")
MIN_PROTECTED_LENGTH = 8  # shorter values would refuse ordinary ids


class PayloadRefusedError(ValueError):
    """A payload carries a credential; the message names the path and never the value."""


def assert_ids_only(payload: object, protected: Iterable[str] = ()) -> None:
    """Raise unless ``payload`` holds nothing credential-like.

    Args:
        payload: A JSON-able value (dicts, lists, strings, numbers, booleans, None).
        protected: Exact secret values (keys, passwords) that must not appear anywhere in it.

    Raises:
        PayloadRefusedError: Naming where the problem is (``payload.items[0]``), never the value.
    """
    literals = tuple(value for value in protected if len(value) >= MIN_PROTECTED_LENGTH)
    _walk(payload, "payload", literals)


def _walk(value: object, path: str, protected: tuple[str, ...]) -> None:
    if isinstance(value, str):
        _check_text(value, path, protected)
    elif isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        for name, item in mapping.items():
            _check_name(str(name), path)
            _check_text(str(name), f"{path} (field name)", protected)
            _walk(item, f"{path}.{name}", protected)
    elif isinstance(value, list | tuple | set | frozenset):
        items = cast("Iterable[object]", value)
        for index, item in enumerate(items):
            _walk(item, f"{path}[{index}]", protected)


def _check_name(name: str, path: str) -> None:
    lowered = name.lower()
    if any(word in lowered for word in DENIED_FIELD_WORDS):
        raise PayloadRefusedError(f"{path}: a field named like a credential is not allowed")


def _check_text(text: str, path: str, protected: tuple[str, ...]) -> None:
    if any(literal in text for literal in protected):
        raise PayloadRefusedError(f"{path}: contains a protected value")
    if any(pattern.search(text) for pattern in KEY_PATTERNS):
        raise PayloadRefusedError(f"{path}: contains a key-shaped string")
