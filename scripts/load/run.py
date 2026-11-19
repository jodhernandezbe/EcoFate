"""Multi-user load test of the running stack (docs/load-test.md).

    uv run python -m scripts.load.run --users 10            # scripted model (no cost)
    uv run python -m scripts.load.run --users 10 --real --budget-usd 8

Each simulated user signs in, asks for an assessment (a background job), asks a short question
while the job runs, asks for its status, and waits for the follow-up turn that explains the
result; an interrupted turn is resumed once. Users start spread over the ramp. Everything is
timed from the client's side, through the real API and the two event streams. ``--real`` uses
the real model with the key in ``OPENAI_API_KEY`` (the stack must run with LOAD_FAKE_MODEL=0)
and starts no new turn once the estimated cost reaches ``--budget-usd``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import random
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx

from scripts.load.client import (
    Account,
    create_account,
    frames,
    load_accounts,
    new_client,
    save_accounts,
    sign_in,
)
from scripts.load.report import Measurements, write
from scripts.load.stats import Sampler

# Vinyl chloride: 33 TRI facilities, so the agent takes the batch assessment (the background job).
# The scripted model ignores the chemical (it replays the recorded call); the real one does not.
ASSESS = "Assess the inhalation exposure and health risk from air releases of CAS 75-01-4."
QUESTION = "While that runs: what does screening-level mean?"
STATUS = "What is the status of the assessment?"
FAKE_KEY = "sk-load-test-scripted-model"  # pragma: allowlist secret  # never sent to a provider
SERVICES = ("api", "worker", "tool-worker", "db", "redis")
BUSY_RETRIES = 6
BUSY_WAIT_SECONDS = 5.0


def server_seconds(event_id: str | None) -> float:
    """The server time of a thread event: its Redis stream id is ``<milliseconds>-<n>``; the
    local clock when the id is absent or unreadable."""
    head = (event_id or "").partition("-")[0]
    return int(head) / 1000 if head.isdigit() else time.time()


def safe_for_key(base_url: str) -> bool:
    """Whether a real key may be sent to ``base_url``: over https, or to this machine only."""
    parts = httpx.URL(base_url)
    return parts.scheme == "https" or parts.host in ("127.0.0.1", "localhost", "::1")


@dataclass
class Shared:
    """What every session of one run shares."""

    measured: Measurements
    deadline: float
    budget_usd: float | None
    costs: dict[str, float] = field(default_factory=dict[str, float])

    def spent(self) -> float:
        return sum(self.costs.values())

    def may_start(self) -> bool:
        """False once the deadline passed or the estimated cost reached the budget."""
        if time.monotonic() >= self.deadline:
            return False
        if self.budget_usd is not None and self.spent() >= self.budget_usd:
            self.measured.budget_reached = True
            return False
        return True

    def record_usage(self, thread_id: str, data: Mapping[str, object]) -> None:
        session = cast(Mapping[str, object], data.get("session") or {})
        cost = session.get("cost_usd")
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            self.costs[thread_id] = max(self.costs.get(thread_id, 0.0), float(cost))


@dataclass
class TurnTimer:
    """The times of one turn's stream, from the moment it was sent."""

    kind: str
    sent: float = field(default_factory=time.monotonic)
    started: bool = False
    answered: bool = False
    interrupted: bool = False

    def see(self, data: Mapping[str, object], measured: Measurements) -> None:
        elapsed = time.monotonic() - self.sent
        kind = data.get("type")
        if kind == "turn_status" and data.get("phase") != "queued" and not self.started:
            self.started = True
            measured.time("chat_queue_wait", elapsed)
        elif kind in ("token", "assistant_message") and not self.answered:
            self.answered = True
            measured.time(f"first_answer_{self.kind}", elapsed)
        elif kind == "turn_interrupted":
            self.interrupted = True


class Session:
    """One simulated user's conversation."""

    def __init__(self, client: httpx.AsyncClient, shared: Shared) -> None:
        self.client = client
        self.shared = shared
        self.thread_id = f"load-{uuid.uuid4().hex[:20]}"
        self.done = asyncio.Event()
        self.queued: dict[str, float] = {}
        self.running: dict[str, float] = {}
        self.ended_at: float | None = None
        self.follow_up_started: float | None = None

    async def _stream(self, method: str, url: str, timer: TurnTimer, body: object) -> int:
        measured = self.shared.measured
        async with self.client.stream(method, url, json=body) as response:
            measured.answered(response.status_code)
            if response.status_code != 200:
                await response.aread()
                return response.status_code
            async for frame in frames(response):
                timer.see(frame.data, measured)
                if frame.data.get("type") == "usage":
                    self.shared.record_usage(self.thread_id, frame.data)
                if frame.data.get("type") == "turn_finished":
                    break
        measured.time("turn_duration", time.monotonic() - timer.sent)
        return 200

    async def turn(self, message: str, kind: str) -> TurnTimer | None:
        """Send one message (waiting out a busy thread); None when no turn ran."""
        body = {"thread_id": self.thread_id, "message": message}
        for _ in range(BUSY_RETRIES):
            if not self.shared.may_start():
                return None
            timer = TurnTimer(kind)
            status = await self._stream("POST", "/api/v1/chat/stream", timer, body)
            if status != 409:
                return timer if status == 200 else None
            await asyncio.sleep(BUSY_WAIT_SECONDS)
        return None

    async def resume_if_interrupted(self, timer: TurnTimer | None) -> None:
        if timer is None or not timer.interrupted or not self.shared.may_start():
            return
        self.shared.measured.resumes += 1
        url = f"/api/v1/chat/threads/{self.thread_id}/resume"
        await self._stream("POST", url, TurnTimer("assess"), None)

    def on_thread_event(self, data: Mapping[str, object], event_id: str | None = None) -> None:
        """Time the job and its follow-up from the thread's events, at the server's time of each
        (the stream entry id), so an event read late or replayed on attach is timed right."""
        measured, now = self.shared.measured, server_seconds(event_id)
        kind, job = data.get("kind"), str(data.get("job_id"))
        if kind == "job.queued":
            measured.jobs_queued += 1
            self.queued[job] = now
        elif kind == "job.running" and job in self.queued:
            measured.time("tools_queue_wait", now - self.queued[job])
            self.running[job] = now
        elif kind == "job.ended":
            self._job_ended(job, str(data.get("status")), now)
        elif kind == "turn.started" and data.get("automatic"):
            self._follow_up_started(str(data.get("turn_id")), now)
        elif kind == "turn.ended" and data.get("automatic"):
            self._follow_up_ended(now)

    def _job_ended(self, job: str, status: str, now: float) -> None:
        measured = self.shared.measured
        measured.jobs_ended[status] = measured.jobs_ended.get(status, 0) + 1
        if job in self.running:
            measured.time("job_duration", now - self.running[job])
        self.ended_at = now
        if status == "cancelled":
            self.done.set()

    def _follow_up_started(self, turn_id: str, now: float) -> None:
        measured = self.shared.measured
        measured.follow_ups_started += 1
        self.follow_up_started = now
        if self.ended_at is not None:
            measured.time("follow_up_wait", now - self.ended_at)
        asyncio.get_running_loop().create_task(self._follow_up_usage(turn_id))

    def _follow_up_ended(self, now: float) -> None:
        if self.follow_up_started is not None:
            self.shared.measured.time("follow_up_duration", now - self.follow_up_started)
        self.done.set()

    async def _follow_up_usage(self, turn_id: str) -> None:
        """Read the follow-up turn's stream for its cost (the browser attaches the same way)."""
        with contextlib.suppress(httpx.HTTPError):
            async with self.client.stream("GET", f"/api/v1/chat/turns/{turn_id}/events") as r:
                async for frame in frames(r):
                    if frame.data.get("type") == "usage":
                        self.shared.record_usage(self.thread_id, frame.data)
                    if frame.data.get("type") == "turn_finished":
                        return

    async def watch(self) -> None:
        """Follow the thread's events, reattaching with Last-Event-ID after a drop."""
        last: str | None = None
        url = f"/api/v1/chat/threads/{self.thread_id}/events"
        while not self.done.is_set():
            headers = {"Last-Event-ID": last} if last else {}
            with contextlib.suppress(httpx.HTTPError):
                async with self.client.stream("GET", url, headers=headers) as response:
                    async for frame in frames(response):
                        last = frame.event_id or last
                        self.on_thread_event(frame.data, frame.event_id)
            await asyncio.sleep(1.0)

    async def script(self) -> None:
        """The conversation: assessment, a question, a status question, then the follow-up."""
        timer = await self.turn(ASSESS, "assess")
        await self.resume_if_interrupted(timer)
        if timer is None:
            return
        watcher = asyncio.create_task(self.watch())
        try:
            await asyncio.sleep(random.uniform(5, 15))  # noqa: S311  # nosec B311  # think time, not security
            await self.resume_if_interrupted(await self.turn(QUESTION, "question"))
            await asyncio.sleep(random.uniform(5, 15))  # noqa: S311  # nosec B311
            await self.resume_if_interrupted(await self.turn(STATUS, "status"))
            left = self.shared.deadline - time.monotonic()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.done.wait(), timeout=max(left, 0))
        finally:
            watcher.cancel()

    async def clear(self) -> None:
        """Discard the thread (cancelling its open jobs), so the next run starts clean."""
        with contextlib.suppress(httpx.HTTPError):
            await self.client.delete(f"/api/v1/chat/threads/{self.thread_id}")


async def ensure_accounts(base_url: str, mailpit_url: str, count: int) -> list[Account]:
    """``count`` verified accounts, creating the missing ones."""
    accounts = load_accounts()
    async with new_client(base_url, 30) as client, httpx.AsyncClient(base_url=mailpit_url) as mail:
        for number in range(len(accounts), count):
            accounts.append(await create_account(client, mail, number))
            save_accounts(accounts)
    return accounts[:count]


async def user(
    account: Account,
    key: str,
    start_after: float,
    base_url: str,
    shared: Shared,
) -> None:
    """One user: wait for its place in the ramp, sign in, run the conversation, clean up."""
    await asyncio.sleep(start_after)
    async with new_client(base_url, 60) as client:
        await sign_in(client, account, key)
        session = Session(client, shared)
        try:
            await session.script()
        finally:
            await session.clear()


async def run(args: argparse.Namespace) -> Path:
    """Run the load test and write its report; return the summary's path."""
    key = os.environ.get("OPENAI_API_KEY", "") if args.real else FAKE_KEY
    if args.real and (not key or args.budget_usd is None):
        raise SystemExit("--real needs OPENAI_API_KEY in the environment and --budget-usd")
    if args.real and not safe_for_key(args.base_url):
        raise SystemExit("--real sends your key: --base-url must be loopback or https")
    accounts = await ensure_accounts(args.base_url, args.mailpit_url, args.users)
    shared = Shared(Measurements(), time.monotonic() + args.max_minutes * 60, args.budget_usd)
    sampler, stop = Sampler(SERVICES), asyncio.Event()
    sampling = asyncio.create_task(sampler.run(5.0, stop))
    ramp = args.ramp_seconds / max(args.users, 1)
    users = [user(a, key, i * ramp, args.base_url, shared) for i, a in enumerate(accounts)]
    await asyncio.gather(*users, return_exceptions=False)
    stop.set()
    await sampling
    shared.measured.cost_usd = shared.spent()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    mode = "real" if args.real else "scripted"
    title = f"{args.users} users, {mode} model ({stamp} UTC)"
    return write(
        Path(args.out) / f"{stamp}-{args.users}u-{mode}",
        title,
        shared.measured,
        sampler.result(),
    )


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m scripts.load.run", description=__doc__)
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mailpit-url", default="http://127.0.0.1:8025")
    parser.add_argument("--ramp-seconds", type=float, default=30.0)
    parser.add_argument("--max-minutes", type=float, default=15.0)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--budget-usd", type=float, default=None)
    parser.add_argument("--out", default="scripts/load/reports")
    args = parser.parse_args(argv)
    if not 1 <= args.users <= 200:
        parser.error("--users must be between 1 and 200")
    return args


if __name__ == "__main__":
    print(asyncio.run(run(parse())))
