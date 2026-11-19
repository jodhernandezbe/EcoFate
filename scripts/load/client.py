"""The load test's HTTP side: accounts through the real API, and the two event streams it reads.

Everything goes through ``/api/v1`` as the browser does (session cookie, the API's own
``Origin``). Sign-up verification reads the link from Mailpit's inbox (``--profile dev``), so
the real sign-up path runs. Passwords are generated per account and kept only in the local
accounts file, which lives under ``.cache/`` (ignored by git).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx

VERIFY_LINK = re.compile(r"#verify=([A-Za-z0-9_\-.~]+)")
ACCOUNTS_FILE = Path(".cache/load-test-accounts.json")
EMAIL_DOMAIN = "load.example.com"
MAIL_WAIT_SECONDS = 30.0


@dataclass(frozen=True)
class Account:
    """One load-test account (local only)."""

    email: str
    password: str


@dataclass(frozen=True)
class Frame:
    """One server-sent event: its id (absent for some) and its JSON data."""

    event_id: str | None
    data: dict[str, object]


def new_client(base_url: str, timeout_seconds: float) -> httpx.AsyncClient:
    """A browser-like client: the API's own Origin on every request, cookies kept."""
    timeout = httpx.Timeout(timeout_seconds, read=None)
    return httpx.AsyncClient(base_url=base_url, headers={"Origin": base_url}, timeout=timeout)


async def frames(response: httpx.Response) -> AsyncIterator[Frame]:
    """The SSE frames of a streaming response (comments and keepalives skipped)."""
    event_id: str | None = None
    data: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line and data:
            yield Frame(event_id, cast(dict[str, object], json.loads("".join(data))))
            event_id, data = None, []


def load_accounts(path: Path = ACCOUNTS_FILE) -> list[Account]:
    """The accounts created by earlier runs (none when the file is missing)."""
    if not path.is_file():
        return []
    raw = cast(list[Mapping[str, str]], json.loads(path.read_text(encoding="utf-8")))
    return [Account(item["email"], item["password"]) for item in raw]


def save_accounts(accounts: list[Account], path: Path = ACCOUNTS_FILE) -> None:
    """Keep the accounts for the next run (owner-only file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"email": a.email, "password": a.password} for a in accounts]
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(rows, indent=1))
    path.chmod(0o600)  # a file left by an earlier run keeps its mode on open


async def _inbox(mailpit: httpx.AsyncClient, email: str) -> list[Mapping[str, object]]:
    """The messages to ``email``, waiting up to ``MAIL_WAIT_SECONDS`` for the first."""
    for _ in range(int(MAIL_WAIT_SECONDS)):
        found = await mailpit.get("/api/v1/search", params={"query": f'to:"{email}"'})
        found.raise_for_status()
        messages = cast(list[Mapping[str, object]], found.json()["messages"])
        if messages:
            return messages
        await asyncio.sleep(1.0)
    raise RuntimeError(f"no verification email for {email}")


async def _verify_token(mailpit: httpx.AsyncClient, email: str) -> str:
    messages = await _inbox(mailpit, email)
    message = await mailpit.get(f"/api/v1/message/{messages[0]['ID']}")
    message.raise_for_status()
    match = VERIFY_LINK.search(str(message.json().get("Text", "")))
    if match is None:
        raise RuntimeError(f"no verification link for {email}")
    return match.group(1)


async def create_account(
    client: httpx.AsyncClient,
    mailpit: httpx.AsyncClient,
    number: int,
) -> Account:
    """Sign up one account and verify it through the emailed link."""
    account = Account(f"load-{number:03d}@{EMAIL_DOMAIN}", secrets.token_urlsafe(18))
    body = {"email": account.email, "password": account.password}
    (await client.post("/api/v1/auth/signup", json=body)).raise_for_status()
    token = await _verify_token(mailpit, account.email)
    (await client.post("/api/v1/auth/verify", json={"token": token})).raise_for_status()
    return account


async def sign_in(client: httpx.AsyncClient, account: Account, api_key: str) -> None:
    """Sign in (the session cookie stays on ``client``) and save the account's model key."""
    body = {"email": account.email, "password": account.password}
    (await client.post("/api/v1/auth/signin", json=body)).raise_for_status()
    saved = await client.post("/api/v1/settings/openai-key", json={"api_key": api_key})
    saved.raise_for_status()
