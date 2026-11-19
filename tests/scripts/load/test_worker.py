"""Tests for scripts/load/worker.py: the fake app is chosen only by LOAD_FAKE_MODEL=1."""

from __future__ import annotations

import pytest

from scripts.load.worker import FAKE_APP, FAKE_FLAG, load_argv
from worker.pool import APP, POOLS


@pytest.mark.parametrize("pool", POOLS)
def test_flag_one_swaps_the_app(pool: str) -> None:
    command = load_argv(pool, {FAKE_FLAG: "1"})
    assert FAKE_APP in command
    assert APP not in command


@pytest.mark.parametrize("environ", [{}, {FAKE_FLAG: "0"}, {FAKE_FLAG: "true"}])
def test_otherwise_production_app(environ: dict[str, str]) -> None:
    command = load_argv(POOLS[0], environ)
    assert APP in command
    assert FAKE_APP not in command
