"""Cooperative stopping: the default never stops, a True check raises."""

from __future__ import annotations

import pytest

from commons.stop import StoppedError, never_stop, raise_if_stopped


def test_the_default_check_never_stops() -> None:
    assert never_stop() is False
    raise_if_stopped(never_stop)


def test_a_check_that_says_stop_raises() -> None:
    with pytest.raises(StoppedError):
        raise_if_stopped(lambda: True)


def test_the_check_is_asked_every_time() -> None:
    answers = iter([False, False, True])
    raise_if_stopped(lambda: next(answers))
    raise_if_stopped(lambda: next(answers))
    with pytest.raises(StoppedError):
        raise_if_stopped(lambda: next(answers))
