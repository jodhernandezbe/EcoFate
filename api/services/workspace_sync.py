"""The thread's workspace, rebuilt from its stored tool results and the user's answers.

The worker stores the tool calls and results; the API rebuilds the workspace from them (the
projectors live here, not in the worker). Rebuilding is deterministic, so any reader of a turn,
and the snapshot of a thread nobody watched, arrive at the same state; it is stored only when
it changed.
"""

from __future__ import annotations

from api.schemas.workspace import WorkspaceState
from api.services.projectors.rules import WorkspaceRules
from api.services.state_serializer import build_workspace
from api.services.threads import ThreadStore
from storage.keys import ThreadKey


async def current_workspace(
    threads: ThreadStore,
    key: ThreadKey,
    rules: WorkspaceRules,
) -> WorkspaceState:
    """The workspace of the thread's tool results so far (stored when it changed)."""
    previous = await threads.workspace(key)
    supplied, _ = await threads.answers(key)
    state = build_workspace(await threads.tool_messages(key), rules, previous, supplied)
    if state != previous:
        await threads.set_workspace(key, state)
    return state
