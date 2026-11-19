"""The command line of one worker pool, built from ``[worker.<pool>]``.

``python -m worker chat`` and ``python -m worker tools`` start ``celery ... worker`` on that
pool's queue with its concurrency and prefetch, so the queue names and sizes live only in
``config/settings.toml``, never in the compose files or the Dockerfile.
"""

from __future__ import annotations

from config.worker import PoolSettings, WorkerSettings

APP = "worker.celery_app"
POOLS = ("chat", "tools")
FIXED_ARGS = ("--loglevel=INFO", "--without-gossip", "--without-mingle")


def pool_settings(settings: WorkerSettings, pool: str) -> PoolSettings:
    """The settings of the pool called ``pool``.

    Raises:
        ValueError: ``pool`` is not one of ``POOLS``.
    """
    if pool not in POOLS:
        raise ValueError(f"pool must be one of {', '.join(POOLS)}")
    return settings.chat if pool == "chat" else settings.tools


def celery_argv(settings: WorkerSettings, pool: str) -> list[str]:
    """The ``celery`` arguments that start ``pool``: only its queue, its size and prefetch."""
    own = pool_settings(settings, pool)
    return [
        "celery",
        "-A",
        APP,
        "worker",
        "-Q",
        own.queue,
        "-c",
        str(own.concurrency),
        f"--prefetch-multiplier={own.prefetch_multiplier}",
        *FIXED_ARGS,
    ]
