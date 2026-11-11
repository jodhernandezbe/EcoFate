"""The worker's modules build their Celery app on import from ``REDIS_URL``: an in-memory
broker is named before any test imports them (no Redis, no running worker)."""

from __future__ import annotations

import os

os.environ.setdefault("REDIS_URL", "memory://")
