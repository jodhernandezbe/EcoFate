"""The load test's stand-ins inside the worker: the scripted model, the assessment's preflight and
its job, each waiting its recorded latency (``timings.toml``) instead of calling anything.

``install()`` patches them into ``worker.resources`` and rebuilds the tool registry; it runs in
the Celery main process before the children fork (``scripts.load.celery_app``), so every child
inherits it. Everything else (API, queues, PostgreSQL, Redis, leases, quota, the thread stream,
follow-up turns) is the real code.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from pydantic import SecretStr

from commons.stop import StopCheck, raise_if_stopped
from config.agent import AgentSettings
from scripts.load.fake_model import ScriptedChatModel

HERE = Path(__file__).parent
SLICE_SECONDS = 1.0
JOB_OVERRIDE = "LOAD_JOB_SECONDS"


@dataclass(frozen=True)
class Timings:
    """Recorded latencies, in seconds."""

    model_seconds: float
    preflight_seconds: float
    job_seconds: float


@dataclass(frozen=True)
class Recorded:
    """One recorded ``assess_facilities`` call: its arguments and the model's view of its result."""

    args: dict[str, object]
    view: dict[str, object]


def load_timings(
    path: Path = HERE / "timings.toml",
    environ: Mapping[str, str] | None = None,
) -> Timings:
    """The recorded latencies (seconds, 0 to 3600); ``LOAD_JOB_SECONDS`` overrides the job's
    (a quick smoke run of the harness, never a measured run)."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    names = ("model_seconds", "preflight_seconds", "job_seconds")
    values = {name: float(raw[name]) for name in names}
    override = (os.environ if environ is None else environ).get(JOB_OVERRIDE, "").strip()
    if override:
        values["job_seconds"] = float(override)
    if any(not 0 <= value < 3600 for value in values.values()):
        raise ValueError("timings must be between 0 and 3600 seconds")
    return Timings(**values)


def load_recorded(path: Path = HERE / "recorded_assessment.json") -> Recorded:
    """The recorded assessment the fake job answers with."""
    raw = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return Recorded(
        args=cast(dict[str, object], raw["args"]),
        view=cast(dict[str, object], raw["view"]),
    )


def fake_preflight(seconds: float) -> object:
    """The job's preflight: the recorded lookup time, then "a job may start"."""

    def preflight(arguments: Mapping[str, object], config: RunnableConfig) -> None:
        time.sleep(seconds)

    return preflight


def fake_job(seconds: float, recorded: Recorded) -> object:
    """The job: the recorded run time (asking the stop check every second), then its result."""

    def run(arguments: Mapping[str, object], should_stop: StopCheck) -> tuple[object, object]:
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            raise_if_stopped(should_stop)
            time.sleep(min(SLICE_SECONDS, left))
        return dict(recorded.view), {}

    return run


def fake_model(timings: Timings, recorded: Recorded) -> object:
    """The worker's model builder: the scripted model, whatever key the user saved."""

    def build(settings: AgentSettings, key: SecretStr) -> BaseChatModel:
        return ScriptedChatModel(model_seconds=timings.model_seconds, assess_args=recorded.args)

    return build


def install() -> None:
    """Patch the stand-ins into the worker and rebuild the tool registry with the fake preflight."""
    import tools.registry as registry
    import worker.resources as resources

    timings, recorded = load_timings(), load_recorded()
    job = fake_job(timings.job_seconds, recorded)
    registry.PREFLIGHTS = {"assess_facilities": fake_preflight(timings.preflight_seconds)}  # type: ignore[assignment]
    registry.registry = registry._build_default_registry()  # pyright: ignore[reportPrivateUsage]
    registry.JOB_RUNNERS = {"assess_facilities": job}  # type: ignore[assignment]
    resources.job_runners = registry.get_job_runners  # type: ignore[assignment]
    resources._build_model = fake_model(timings, recorded)  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
