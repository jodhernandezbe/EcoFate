"""The report of a held thread, or why it cannot be given (with the HTTP status to answer)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from api.schemas.workspace import WorkspaceState
from api.services.report.builder import build_report, file_name, has_findings, report_context
from api.services.snapshots import last_answer
from api.services.threads import ThreadStore
from config.ui import UiSettings
from storage.keys import ThreadKey

NOT_HELD = "That run is no longer available."
RUNNING = "A turn is already running for this thread."
NOTHING = "There are no findings to report yet."


class ReportUnavailable(Exception):
    """No report for this thread; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class ReportFile:
    """A built report: its attachment name and the ``.docx`` bytes."""

    name: str
    content: bytes


async def _state(threads: ThreadStore, key: ThreadKey) -> WorkspaceState:
    if not await threads.holds(key):
        raise ReportUnavailable(404, NOT_HELD)
    if await threads.running(key):
        raise ReportUnavailable(409, RUNNING)
    await threads.touch(key)
    state = await threads.workspace(key) or WorkspaceState()
    if not has_findings(state):
        raise ReportUnavailable(409, NOTHING)
    return state


async def thread_report(
    threads: ThreadStore,
    key: ThreadKey,
    settings: UiSettings,
    when: datetime,
) -> ReportFile:
    """Build the report of a held, idle thread with findings; never runs the agent or a tool.

    Raises:
        ReportUnavailable: 404 when the thread is not held, 409 while it runs a turn or when it
            has nothing to report.
    """
    state = await _state(threads, key)
    ctx = report_context(settings)
    content = build_report(state, last_answer(await threads.messages(key)), ctx, when)
    return ReportFile(name=file_name(state, ctx, when), content=content)
