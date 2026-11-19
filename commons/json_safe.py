"""Make a value storable as strict JSON: plain containers, finite numbers, string keys.

Results of tools hold only data, but a NaN or an infinity (not JSON, and refused by PostgreSQL's
``jsonb``) can slip into a computed field. Such a number becomes ``None``: absent, never guessed.
Anything that is not data (an object, a set, a non-string key) raises, so a bug is not stored.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast


def json_safe(value: object) -> object:
    """A deep copy of ``value`` as strict-JSON data (dicts, lists, strings, finite numbers, bools,
    None); non-finite floats become None.

    Raises:
        TypeError: ``value`` holds something that is not JSON data (or a non-string key).
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {_key(k): json_safe(v) for k, v in cast(Mapping[object, object], value).items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [json_safe(item) for item in cast(Sequence[object], value)]
    raise TypeError(f"{type(value).__name__} is not JSON data")


def _key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("a JSON object key must be a string")
    return key
