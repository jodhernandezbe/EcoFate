"""Cooperative stopping: a long computation asks a ``StopCheck`` at its natural boundaries.

The caller (a job runner) owns the reason to stop (a time limit, a cancel request); the
computation only asks, at points where stopping loses nothing half-done, and raises
``StoppedError`` when told to. The default never stops. Pure: no clock, no I/O.
"""

from __future__ import annotations

from collections.abc import Callable

StopCheck = Callable[[], bool]


class StoppedError(Exception):
    """The computation was asked to stop at a boundary and did; nothing partial is returned."""


def never_stop() -> bool:
    """The default ``StopCheck``: never asks to stop."""
    return False


def raise_if_stopped(should_stop: StopCheck) -> None:
    """Raise ``StoppedError`` when ``should_stop`` says so.

    Raises:
        StoppedError: The check returned True.
    """
    if should_stop():
        raise StoppedError
