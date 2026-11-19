"""``python -m scripts.load.worker <chat|tools>``: a worker pool for the load test.

The same Celery command line as ``python -m worker`` (queue, concurrency and prefetch from
``[worker.<pool>]``), but with ``LOAD_FAKE_MODEL=1`` its app is ``scripts.load.celery_app``,
which installs the scripted model and the recorded assessment first. Without it, the pool is the
production worker unchanged (the real-model run).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

from config.worker import get_worker_settings
from worker.pool import APP, POOLS, celery_argv

FAKE_APP = "scripts.load.celery_app"
FAKE_FLAG = "LOAD_FAKE_MODEL"


def load_argv(pool: str, environ: Mapping[str, str]) -> list[str]:
    """The pool's ``celery`` arguments, with the fake app when ``LOAD_FAKE_MODEL=1``."""
    command = celery_argv(get_worker_settings(), pool)
    if environ.get(FAKE_FLAG) == "1":
        command[command.index(APP)] = FAKE_APP
    return command


def main(argv: Sequence[str]) -> None:
    """Exec the load-test worker of the pool named in ``argv``."""
    if len(argv) != 1 or argv[0] not in POOLS:
        raise SystemExit(f"usage: python -m scripts.load.worker {'|'.join(POOLS)}")
    command = load_argv(argv[0], os.environ)
    os.execvp(command[0], command)  # nosec B606  # fixed argv built from settings, no shell


if __name__ == "__main__":
    main(sys.argv[1:])
