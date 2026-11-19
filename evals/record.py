"""What one evaluation run did: the tool calls in order and the final report."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolCall:
    """One tool call made by the agent.

    Attributes:
        name: Tool name.
        args: Arguments as the model sent them.
        output: Tool output, parsed from JSON when possible (else the raw text).
        unrecorded: True when a replayed tool had no recording for these arguments.
    """

    name: str
    args: Mapping[str, object]
    output: object
    unrecorded: bool


@dataclass(frozen=True)
class RunRecord:
    """One scenario run.

    Attributes:
        scenario_id: Catalogue id of the scenario.
        query: The user message sent to the agent.
        calls: Tool calls in the order made.
        report: Text of the final answer; empty if the run ended without one.
        error: Why the run ended early, or None when it finished.
        interim: The first turn's final reply when a second turn followed it (a background job
            ended and was explained); empty otherwise.
    """

    scenario_id: str
    query: str
    calls: tuple[ToolCall, ...]
    report: str
    error: str | None
    interim: str = ""

    @property
    def completed(self) -> bool:
        """True when the run finished with a non-empty final report."""
        return self.error is None and bool(self.report.strip())

    def calls_to(self, name: str) -> tuple[ToolCall, ...]:
        """Return the calls to tool ``name``, in order."""
        return tuple(call for call in self.calls if call.name == name)

    def to_json(self) -> str:
        """Serialize the record (for the evaluation dataset and debugging)."""
        return json.dumps(asdict(self), default=str, ensure_ascii=False)
