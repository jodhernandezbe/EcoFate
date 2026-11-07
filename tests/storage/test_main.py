"""Tests for the migration commands (Alembic and the database are replaced)."""

from __future__ import annotations

import pytest

import storage.__main__ as cli


class _Calls:
    def __init__(self) -> None:
        self.upgrades: list[str] = []
        self.downgrades: list[str] = []


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    seen = _Calls()

    def upgrade(_config: object, revision: str) -> None:
        seen.upgrades.append(revision)

    def downgrade(_config: object, revision: str) -> None:
        seen.downgrades.append(revision)

    monkeypatch.setattr(cli.command, "upgrade", upgrade)
    monkeypatch.setattr(cli.command, "downgrade", downgrade)
    return seen


def test_upgrade_goes_to_head(calls: _Calls) -> None:
    assert cli.main(["upgrade"]) == 0
    assert calls.upgrades == ["head"]


def test_downgrade_passes_the_revision(calls: _Calls) -> None:
    assert cli.main(["downgrade", "base"]) == 0
    assert calls.downgrades == ["base"]


def test_a_missing_url_is_reported_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(*_args: object) -> None:
        raise cli.DatabaseSetupError("Set DATABASE_URL to the PostgreSQL connection URL")

    monkeypatch.setattr(cli.command, "upgrade", refuse)
    assert cli.main(["upgrade"]) == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def _head() -> str:
    return "0001"


@pytest.mark.parametrize(
    ("stored", "exit_code", "printed"),
    [("0001", 0, "0001"), ("0000", 1, "0000"), (None, 1, "(none)")],
)
def test_current_exits_1_unless_at_head(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stored: str | None,
    exit_code: int,
    printed: str,
) -> None:
    async def fake_read() -> str | None:
        return stored

    monkeypatch.setattr(cli, "_read_current_revision", fake_read)
    monkeypatch.setattr(cli, "head_revision", _head)
    assert cli.main(["current"]) == exit_code
    assert capsys.readouterr().out.strip() == printed


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        cli.main([])
