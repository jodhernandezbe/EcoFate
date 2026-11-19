"""``python -m worker <chat|tools>``: replace this process with that pool's Celery worker."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from config.worker import get_worker_settings
from worker.pool import POOLS, celery_argv


def main(argv: Sequence[str]) -> None:
    """Exec the worker of the pool named in ``argv`` (exit with a usage message otherwise)."""
    if len(argv) != 1 or argv[0] not in POOLS:
        raise SystemExit(f"usage: python -m worker {'|'.join(POOLS)}")
    command = celery_argv(get_worker_settings(), argv[0])
    os.execvp(command[0], command)  # nosec B606  # fixed argv built from settings, no shell


if __name__ == "__main__":
    main(sys.argv[1:])
