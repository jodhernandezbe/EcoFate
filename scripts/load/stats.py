"""CPU and memory of the stack's containers during a run, sampled from ``docker stats``."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

UNITS = {
    "b": 1 / 2**20,
    "kib": 1 / 1024,
    "mib": 1.0,
    "gib": 1024.0,
    "kb": 1e3 / 2**20,
    "mb": 1e6 / 2**20,
    "gb": 1e9 / 2**20,
}
SIZE = re.compile(r"^\s*([0-9.]+)\s*([A-Za-z]+)")
DOCKER = ("docker", "stats", "--no-stream", "--format", "{{json .}}")


def mebibytes(text: str) -> float | None:
    """``"1.5GiB / 12GiB"`` -> 1536.0 (the used part); None when it cannot be read."""
    match = SIZE.match(text.split("/")[0])
    if match is None or match.group(2).lower() not in UNITS:
        return None
    return float(match.group(1)) * UNITS[match.group(2).lower()]


def percent(text: str) -> float | None:
    """``"153.2%"`` -> 153.2; None when it cannot be read."""
    try:
        return float(text.strip().rstrip("%"))
    except ValueError:
        return None


@dataclass
class Sampler:
    """Samples of the containers whose name contains one of ``services``."""

    services: Sequence[str]
    cpu: dict[str, list[float]] = field(default_factory=dict[str, list[float]])
    memory: dict[str, list[float]] = field(default_factory=dict[str, list[float]])

    def service_of(self, container: str) -> str | None:
        """The service a container belongs to (the longest matching name)."""
        found = [s for s in self.services if s in container]
        return max(found, key=len) if found else None

    def add(self, row: Mapping[str, str]) -> None:
        """Record one ``docker stats`` row."""
        service = self.service_of(row.get("Name", ""))
        cpu, memory = percent(row.get("CPUPerc", "")), mebibytes(row.get("MemUsage", ""))
        if service is None or cpu is None or memory is None:
            return
        self.cpu.setdefault(service, []).append(cpu)
        self.memory.setdefault(service, []).append(memory)

    async def sample_once(self) -> None:
        """One ``docker stats`` snapshot."""
        process = await asyncio.create_subprocess_exec(
            *DOCKER,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await process.communicate()
        for line in out.decode().splitlines():
            if line.strip():
                self.add(json.loads(line))

    async def run(self, interval_seconds: float, stop: asyncio.Event) -> None:
        """Sample every ``interval_seconds`` until ``stop`` is set."""
        while not stop.is_set():
            await self.sample_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue

    def result(self) -> dict[str, dict[str, float]]:
        """Peak and mean CPU (%) and peak memory (MiB) per service."""
        return {
            name: {
                "cpu_peak": max(values),
                "cpu_mean": sum(values) / len(values),
                "mem_peak_mib": max(self.memory[name]),
            }
            for name, values in self.cpu.items()
        }
