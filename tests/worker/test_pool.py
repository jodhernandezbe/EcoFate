"""Each worker pool consumes only its own queue, sized from ``[worker.<pool>]``."""

from __future__ import annotations

import pytest

from config.worker import get_worker_settings
from worker.pool import celery_argv, pool_settings


@pytest.mark.parametrize("pool", ["chat", "tools"])
def test_a_pool_consumes_only_its_queue_with_its_size(pool: str) -> None:
    settings = get_worker_settings()
    own = pool_settings(settings, pool)
    argv = celery_argv(settings, pool)
    assert argv[argv.index("-Q") + 1] == own.queue
    assert argv[argv.index("-c") + 1] == str(own.concurrency)
    assert f"--prefetch-multiplier={own.prefetch_multiplier}" in argv
    assert argv.count("-Q") == 1


def test_the_pools_use_different_queues() -> None:
    settings = get_worker_settings()
    chat, tools = (celery_argv(settings, pool) for pool in ("chat", "tools"))
    assert chat[chat.index("-Q") + 1] != tools[tools.index("-Q") + 1]


def test_an_unknown_pool_is_refused() -> None:
    with pytest.raises(ValueError, match="pool must be one of"):
        celery_argv(get_worker_settings(), "other")
