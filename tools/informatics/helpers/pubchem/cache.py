"""On-disk (SQLite) cache of PubChem answers, so repeated runs do not ask again."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

_OK = 200
_NOT_FOUND = 404
_SECONDS_PER_DAY = 86_400.0
_BUSY_TIMEOUT_SECONDS = 5.0
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS responses ("
    "url TEXT PRIMARY KEY, status INTEGER NOT NULL, body TEXT, fetched_at REAL NOT NULL)"
)
_CACHE_ERRORS = (sqlite3.Error, OSError)


@dataclass(frozen=True)
class CachedAnswer:
    """A cached answer: a decoded body (status 200) or a known "not found" (status 404)."""

    status: int
    payload: object


class ResponseCache:
    """Answers keyed by full request URL, valid for a lifetime; never fails a lookup.

    Only successful answers and definitive "not found" answers are stored. Any problem with
    the file (corrupt, not writable, locked) is logged once and treated as an empty cache.
    """

    def __init__(
        self,
        path: Path,
        ttl_days: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a cache.

        Args:
            path: SQLite file; created, with its folder, on the first write.
            ttl_days: Days an answer stays valid.
            clock: Seconds since the epoch; replaced in tests.
        """
        self._path = path
        self._ttl_seconds = ttl_days * _SECONDS_PER_DAY
        self._clock = clock
        self._warned = False

    def get(self, url: str) -> CachedAnswer | None:
        """Return the unexpired answer for ``url``, or None."""
        row = self._read(url)
        if row is None:
            return None
        status, body, fetched_at = row
        if self._clock() - fetched_at > self._ttl_seconds or status not in (_OK, _NOT_FOUND):
            return None
        if status == _NOT_FOUND:
            return CachedAnswer(_NOT_FOUND, None)
        return self._decoded(body)

    def put_ok(self, url: str, payload: object) -> None:
        """Store a successful JSON answer."""
        try:
            body = json.dumps(payload)
        except (TypeError, ValueError):
            return
        self._write(url, _OK, body)

    def put_not_found(self, url: str) -> None:
        """Store that PubChem has nothing for ``url`` (HTTP 404)."""
        self._write(url, _NOT_FOUND, None)

    def _decoded(self, body: str | None) -> CachedAnswer | None:
        try:
            return CachedAnswer(_OK, cast(object, json.loads(body or "")))
        except ValueError:
            self._warn("a cached answer is not valid JSON")
            return None

    def _read(self, url: str) -> tuple[int, str | None, float] | None:
        if not self._path.is_file():
            return None
        try:
            with closing(self._connect()) as db:
                row = db.execute(
                    "SELECT status, body, fetched_at FROM responses WHERE url = ?",
                    (url,),
                ).fetchone()
        except _CACHE_ERRORS as exc:
            self._warn(f"cannot read the cache ({exc})")
            return None
        return cast(tuple[int, str | None, float], row) if row else None

    def _write(self, url: str, status: int, body: str | None) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as db, db:
                db.execute(
                    "INSERT OR REPLACE INTO responses (url, status, body, fetched_at) "
                    "VALUES (?, ?, ?, ?)",
                    (url, status, body, self._clock()),
                )
        except _CACHE_ERRORS as exc:
            self._warn(f"cannot write the cache ({exc})")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=_BUSY_TIMEOUT_SECONDS)
        db.execute(_SCHEMA)
        return db

    def _warn(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("PubChem response cache disabled for this run: %s", message)
