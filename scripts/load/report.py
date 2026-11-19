"""The load test's measurements and their summary (pure: no I/O but the final write).

Durations are summarised as median, 95th percentile and maximum (nearest-rank); counts as
totals and shares. A measurement nobody produced (no job ended within the run) is reported as
absent, never as 0.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

DURATIONS = {
    "first_answer_assess": "Time to first answer, assessment request (s)",
    "first_answer_question": "Time to first answer, question during a job (s)",
    "first_answer_status": "Time to first answer, status question (s)",
    "chat_queue_wait": "Queue wait, chat queue (s)",
    "turn_duration": "Turn duration, user turns (s)",
    "tools_queue_wait": "Queue wait, tools queue (s)",
    "job_duration": "Job duration (s)",
    "follow_up_wait": "Follow-up start after job end (s)",
    "follow_up_duration": "Follow-up turn duration (s)",
}


@dataclass
class Measurements:
    """Everything one run observed."""

    durations: dict[str, list[float]] = field(default_factory=dict[str, list[float]])
    statuses: dict[str, int] = field(default_factory=dict[str, int])
    requests: int = 0
    follow_ups_started: int = 0
    jobs_queued: int = 0
    jobs_ended: dict[str, int] = field(default_factory=dict[str, int])
    resumes: int = 0
    cost_usd: float = 0.0
    budget_reached: bool = False

    def time(self, name: str, seconds: float) -> None:
        """Record one duration under ``name`` (one of ``DURATIONS``)."""
        if name not in DURATIONS:
            raise ValueError(f"unknown measurement: {name}")
        self.durations.setdefault(name, []).append(seconds)

    def answered(self, status: int) -> None:
        """Count one request's HTTP status."""
        self.requests += 1
        key = str(status)
        self.statuses[key] = self.statuses.get(key, 0) + 1


def percentile(values: Sequence[float], share: float) -> float:
    """The nearest-rank percentile of ``values`` (``share`` in 0..1; values not empty)."""
    ordered = sorted(values)
    rank = max(1, math.ceil(share * len(ordered)))
    return ordered[rank - 1]


def summary(values: Sequence[float]) -> dict[str, float | int] | None:
    """Count, median, 95th percentile and maximum; None when nothing was measured."""
    if not values:
        return None
    return {
        "n": len(values),
        "median": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def shares(statuses: Mapping[str, int], requests: int) -> dict[str, float]:
    """The share of requests answered 409, 429 and 5xx (0 when there were none)."""
    if requests == 0:
        return {"409": 0.0, "429": 0.0, "5xx": 0.0}
    server = sum(count for code, count in statuses.items() if code.startswith("5"))
    return {
        "409": statuses.get("409", 0) / requests,
        "429": statuses.get("429", 0) / requests,
        "5xx": server / requests,
    }


def _row(label: str, stats: Mapping[str, float | int] | None) -> str:
    if stats is None:
        return f"| {label} | not measured | | | |"
    return (
        f"| {label} | {stats['n']} | {stats['median']:.1f} | {stats['p95']:.1f} "
        f"| {stats['max']:.1f} |"
    )


def _resource_rows(resources: Mapping[str, Mapping[str, float]]) -> list[str]:
    rows = ["| Container | CPU peak (%) | CPU mean (%) | Memory peak (MiB) |", "|---|---|---|---|"]
    for name, stats in sorted(resources.items()):
        rows.append(
            f"| {name} | {stats['cpu_peak']:.0f} | {stats['cpu_mean']:.0f} "
            f"| {stats['mem_peak_mib']:.0f} |",
        )
    return rows


def markdown(
    title: str,
    measured: Measurements,
    resources: Mapping[str, Mapping[str, float]],
) -> str:
    """The run's summary as a Markdown section."""
    lines = [
        f"### {title}",
        "",
        "| Measurement | n | Median | p95 | Max |",
        "|---|---|---|---|---|",
    ]
    for name, label in DURATIONS.items():
        lines.append(_row(label, summary(measured.durations.get(name, []))))
    share = shares(measured.statuses, measured.requests)
    lines += [
        "",
        f"Requests: {measured.requests}; answered 409: {share['409']:.1%}, 429: "
        f"{share['429']:.1%}, 5xx: {share['5xx']:.1%}. Jobs queued: {measured.jobs_queued}, "
        f"ended: {dict(sorted(measured.jobs_ended.items()))}. Follow-up turns started: "
        f"{measured.follow_ups_started}. Resumes: {measured.resumes}.",
    ]
    if measured.cost_usd or measured.budget_reached:
        ended = " The budget cap ended the run." if measured.budget_reached else ""
        lines.append(f"Estimated model cost: USD {measured.cost_usd:.2f}.{ended}")
    return "\n".join([*lines, "", *_resource_rows(resources), ""])


def write(
    directory: Path,
    title: str,
    measured: Measurements,
    resources: Mapping[str, Mapping[str, float]],
) -> Path:
    """Write ``measurements.json`` and ``summary.md`` into ``directory``; return the summary."""
    directory.mkdir(parents=True, exist_ok=True)
    raw = {"measurements": asdict(measured), "resources": resources}
    (directory / "measurements.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    page = directory / "summary.md"
    page.write_text(markdown(title, measured, resources), encoding="utf-8")
    return page
