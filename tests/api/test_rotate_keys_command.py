"""Tests for ``python -m api rotate-keys``: it prints counts only and refuses arguments."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

import api.__main__ as entry
import api.rotate_keys_command as command
from app.user_key_vault import RotationReport


def _report(resealed: int = 3, already: int = 2, unreadable: int = 0) -> RotationReport:
    return RotationReport(resealed, already, unreadable)


def test_summary_is_counts_only() -> None:
    assert command.summary(_report(3, 2, 1)) == "Re-sealed 3, already current 2, unreadable 1."


def test_main_prints_the_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def run() -> RotationReport:
        return _report()

    monkeypatch.setattr(command, "_run", run)
    command.main([])
    assert capsys.readouterr().out.strip() == "Re-sealed 3, already current 2, unreadable 0."


def test_main_exits_non_zero_when_rows_are_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def run() -> RotationReport:
        return _report(unreadable=2)

    monkeypatch.setattr(command, "_run", run)
    with pytest.raises(SystemExit) as stopped:
        command.main([])
    assert stopped.value.code == 1
    assert "unreadable 2" in capsys.readouterr().out


def test_main_refuses_arguments() -> None:
    with pytest.raises(SystemExit, match="no arguments"):
        command.main(["--now"])


def test_the_api_entry_point_dispatches_rotate_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(entry, "load_dotenv", lambda: True)

    def record(argv: Sequence[str]) -> None:
        seen.append(list(argv))

    monkeypatch.setattr(entry, "rotate_keys", record)
    entry.main(["rotate-keys"])
    assert seen == [[]]


def test_a_missing_kek_stops_the_command_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.byok import get_byok_settings

    variable = get_byok_settings().kek_env_var
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(SystemExit, match=variable):
        command.main([])
