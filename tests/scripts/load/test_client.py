"""Tests for scripts/load/client.py: SSE frames and the local accounts file."""

from __future__ import annotations

import stat
from pathlib import Path

import httpx
import pytest

from scripts.load.client import Account, Frame, frames, load_accounts, save_accounts

SSE = (
    b": keepalive\n\n"
    b"id: 1700000000123-0\n"
    b'data: {"type": "token", "text": "hi"}\n\n'
    b'data: {"type": "a",\n'
    b'data:  "n": 2}\n\n'
    b"id: 9-1\n"
    b'data: {"type": "turn_finished"}\n\n'
)


async def _collect(body: bytes) -> list[Frame]:
    async def stream() -> object:
        yield body

    response = httpx.Response(200, content=stream())  # pyright: ignore[reportArgumentType]
    return [frame async for frame in frames(response)]


@pytest.mark.anyio
async def test_frames_parse_ids_and_data() -> None:
    result = await _collect(SSE)
    assert [f.event_id for f in result] == ["1700000000123-0", None, "9-1"]
    assert result[0].data == {"type": "token", "text": "hi"}
    assert result[1].data == {"type": "a", "n": 2}
    assert result[2].data == {"type": "turn_finished"}


@pytest.mark.anyio
async def test_frames_skip_keepalive_only() -> None:
    assert await _collect(b": keepalive\n\n: keepalive\n\n") == []


def test_accounts_round_trip_with_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "accounts.json"
    accounts = [Account("a@load.example.com", "pw-a"), Account("b@load.example.com", "pw-b")]
    save_accounts(accounts, path)
    assert load_accounts(path) == accounts
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_load_accounts_missing_file(tmp_path: Path) -> None:
    assert load_accounts(tmp_path / "missing.json") == []
