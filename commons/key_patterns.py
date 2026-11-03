"""Patterns for strings shaped like an API key or credential.

Used wherever text may leave the process (log records, monitoring spans) so they all hide the
same things. Pure data: callers decide what to replace a match with.
"""

from __future__ import annotations

import re

SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{10,}")
# The provider echoes a key back in its error messages with the middle starred out
# ("sk-proj-****p8UA"), which still shows its end; that is scrubbed too.
# (The lookahead keeps it from re-matching its own replacement, so redacting twice is harmless.)
MASKED_KEY_PATTERN = re.compile(r"sk-(?!\*\*\*REDACTED)[A-Za-z0-9_-]*\*+[A-Za-z0-9]*")
# A bearer token or a key-like assignment of any shape ("Authorization: Bearer ...",
# "api_key=...", "'x-api-key': '...'"): the value goes, the name stays.
BEARER_PATTERN = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
# A key in a URL's query string, as the Census Data API takes it ("...&key=...").
QUERY_PATTERN = re.compile(r"(?i)([?&](?:key|api_?key|access_token|token)=)[^&\s'\")]+")
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b((?:x-)?api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)"
    r"(['\"]?\s*[:=]\s*['\"]?)[^\s'\",})]{8,}",
)

KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    SECRET_PATTERN,
    MASKED_KEY_PATTERN,
    BEARER_PATTERN,
    QUERY_PATTERN,
    ASSIGNMENT_PATTERN,
)
