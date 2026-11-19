"""``celery -A scripts.load.celery_app worker``: the real worker with the load test's stand-ins.

Importing this module installs the fakes (``scripts.load.fakes``) and then exposes the worker's
own Celery app, so its signals and tasks are exactly those of production. Load test only: it is
started by ``compose.load.yaml`` when ``LOAD_FAKE_MODEL=1`` (the real-model run leaves it out).
"""

from __future__ import annotations

from scripts.load.fakes import install

install()

from worker.celery_app import celery  # noqa: E402  # after the fakes are installed

__all__ = ["celery"]
