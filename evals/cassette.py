"""Replay of recorded tool outputs, so evaluation runs never hit live services.

A cassette is one JSON file per scenario: ``{tool_name: [{"args": {...}, "output": ...}]}``,
recorded from the live tools (never written by hand). A replayed tool keeps the production
name, description and argument schema, so the model sees exactly the real contract. A call
with no recording fails closed: the agent gets an error result marked ``unrecorded``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from langchain_core.tools import BaseTool, StructuredTool

UNRECORDED_KEY = "unrecorded"


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        items = cast(Mapping[object, object], value).items()
        return {str(k): _canonical(v) for k, v in sorted(items, key=lambda kv: str(kv[0]))}
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in cast(Sequence[object], value)]
    return None if value is None else str(value).strip()


def call_key(args: Mapping[str, object]) -> str:
    """Canonical key of a call's arguments (keys sorted, scalars as stripped strings)."""
    return json.dumps(_canonical(args), sort_keys=True)


@dataclass(frozen=True)
class Cassette:
    """Recorded outputs, keyed by tool name and canonical arguments."""

    outputs: Mapping[str, Mapping[str, object]] = field(
        default_factory=lambda: dict[str, Mapping[str, object]](),
    )

    @classmethod
    def load(cls, path: Path) -> Cassette:
        """Read a cassette file; a missing file is an empty cassette (every call unrecorded)."""
        if not path.is_file():
            return cls()
        raw = cast(dict[str, list[dict[str, object]]], json.loads(path.read_text()))
        return cls(
            {
                tool: {call_key(cast(Mapping[str, object], e["args"])): e["output"] for e in rows}
                for tool, rows in raw.items()
            },
        )

    def lookup(self, tool: str, args: Mapping[str, object]) -> tuple[bool, object]:
        """Return ``(found, output)`` for a call."""
        recorded = self.outputs.get(tool, {})
        key = call_key(args)
        return (key in recorded, recorded.get(key))


def _unrecorded(tool: str, args: Mapping[str, object]) -> dict[str, object]:
    return {
        "error": f"no recording for {tool}({call_key(args)}); re-record the scenario",
        UNRECORDED_KEY: True,
    }


def _clone(tool: BaseTool, func: Callable[..., object]) -> BaseTool:
    return StructuredTool.from_function(
        func=func,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,  # type: ignore[arg-type]
    )


def _replayer(tool: BaseTool, cassette: Cassette) -> Callable[..., object]:
    def replay(**kwargs: object) -> object:
        found, output = cassette.lookup(tool.name, kwargs)
        return output if found else _unrecorded(tool.name, kwargs)

    return replay


class Recorder:
    """Collects live outputs of network tools while a scenario runs in recording mode."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, dict[str, object]]] = {}

    def _recorder(self, tool: BaseTool) -> Callable[..., object]:
        def record(**kwargs: object) -> object:
            output = tool.invoke(dict(kwargs))
            row: dict[str, object] = {"args": _canonical(kwargs), "output": output}
            self._rows.setdefault(tool.name, {})[call_key(kwargs)] = row
            return output

        return record

    def wrap(self, tools: Sequence[BaseTool], live_tools: Collection[str]) -> list[BaseTool]:
        """Return the tools with each network tool recording its live outputs."""
        return [t if t.name in live_tools else _clone(t, self._recorder(t)) for t in tools]

    def seed(self, path: Path) -> None:
        """Start from the recordings of the cassette file ``path`` (none if it is missing).

        What is recorded afterwards is added to them; for the same tool and arguments the new
        output replaces the old one.
        """
        if not path.is_file():
            return
        raw = cast(dict[str, list[dict[str, object]]], json.loads(path.read_text()))
        for tool, rows in raw.items():
            for row in rows:
                args = cast(Mapping[str, object], row["args"])
                self._rows.setdefault(tool, {})[call_key(args)] = row

    def invoke(self, tools: Sequence[BaseTool], name: str, args: Mapping[str, object]) -> None:
        """Call the wrapped tool ``name`` (a recording clone from ``wrap``) with ``args``.

        The clone receives every field of the tool's argument schema, defaults included, so the
        recording carries the key of an agent call that leaves its optional arguments out.
        """
        chosen = next((t for t in tools if t.name == name), None)
        if chosen is None:
            raise KeyError(f"no tool named {name!r} to record")
        chosen.invoke(dict(args))

    def save(self, path: Path) -> None:
        """Write everything recorded (and seeded) as a cassette file, replacing the file."""
        rows = {tool: list(calls.values()) for tool, calls in sorted(self._rows.items())}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str) + "\n")


def replay_tools(
    tools: Sequence[BaseTool],
    cassette: Cassette,
    live_tools: Collection[str],
) -> list[BaseTool]:
    """Return the tools with network tools replayed from ``cassette``.

    Args:
        tools: The production tools.
        cassette: Recorded outputs.
        live_tools: Names of tools that need no network; they are returned unchanged.
    """
    return [t if t.name in live_tools else _clone(t, _replayer(t, cassette)) for t in tools]
