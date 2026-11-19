"""FastAPI ``Depends()`` providers; tests override them with fakes."""

from __future__ import annotations

import os
from dataclasses import replace
from functools import partial
from typing import Annotated, cast

from fastapi import Depends, Request

from agent.jobs import job_runners
from api.core.config import ui_settings
from api.core.session_guard import auth_runtime
from api.services.agent_runner import AgentRuntime
from api.services.auth.throttle import client_address
from api.services.key_setup import KeyServices
from api.services.monitoring.service import MonitoringService
from api.services.projectors.rules import WorkspaceRules
from api.services.quota import QuotaService
from api.services.threads import ThreadStore
from api.services.turn_queue import QueueSetup, TurnQueue
from app.chat_model import build_chat_model
from app.jobs.gateway import JobGateway
from app.jobs.lifecycle import JobLifecycle
from app.jobs.runner import run_background_job
from app.jobs.services import JobServices, JobSettings
from app.task_queue import InProcessEnqueuer, ToolJob, TurnJob
from app.turns.follow_up import FollowUps
from app.turns.job import run_background_turn
from app.turns.keys import load_turn_keys
from app.turns.recording import BackgroundServices
from app.web_turn import web_turn_settings
from config.agent import get_agent_settings
from config.population import get_population_settings
from config.risk_bands import get_risk_bands
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings
from config.worker import get_worker_settings


def get_settings() -> UiSettings:
    """The UI settings."""
    return ui_settings()


def get_key_services(request: Request) -> KeyServices:
    """The user key vault and the operator's keys (built at start-up, never per request)."""
    return cast(KeyServices, request.app.state.keys)


def _workspace_rules(ui: UiSettings) -> WorkspaceRules:
    return WorkspaceRules(
        thresholds=get_risk_bands(),
        coordinate_tolerance_deg=ui.map.coordinate_tolerance_deg,
        default_radius_km=get_population_settings().default_radius_km,
        sector_half_angle_deg=ui.map.sector_half_angle_deg,
        vertex_spacing_deg=ui.map.vertex_spacing_deg,
        graph=ui.exposure_graph,
        air_release=ui.air_release,
    )


def get_runtime() -> AgentRuntime:
    """The configured chat model factory, step limit, labels, prices, guard, prompt and rules
    (the turn settings are the worker's own, from ``app.web_turn``)."""
    settings = get_agent_settings()
    ui = ui_settings()
    turn = web_turn_settings(settings, ui)
    return AgentRuntime(
        build_model=lambda key: build_chat_model(settings, api_key=key),
        recursion_limit=turn.recursion_limit,
        step_labels=ui.step_labels,
        model_name=turn.model_name,
        pricing=turn.pricing,
        scope_guard=turn.scope_guard,
        completion_guard=turn.completion_guard,
        system_prompt=turn.system_prompt,
        workspace_rules=_workspace_rules(ui),
        telemetry=turn.telemetry,
        max_resumes_per_turn=settings.max_resumes_per_turn,
    )


def get_max_resumes() -> int:
    """How many times one interrupted turn may be resumed (``[agent].max_resumes_per_turn``)."""
    return get_agent_settings().max_resumes_per_turn


def get_quota(request: Request) -> QuotaService:
    """The daily turn quota of this app (built at start-up from ``[limits]`` and the store)."""
    return cast(QuotaService, request.app.state.quota)


def get_threads(request: Request) -> ThreadStore:
    """The thread store of this app (PostgreSQL in production, a fake in tests)."""
    return cast(ThreadStore, request.app.state.threads)


def get_monitoring(request: Request) -> MonitoringService:
    """The monitoring service; it finds the Logfire read token in the server's environment and
    resolves the accounts of the sessions through the application database."""
    emails = auth_runtime(request).accounts.users.emails
    settings = get_telemetry_settings()
    return MonitoringService(settings, ui_settings().step_labels, os.environ, emails=emails)


def _in_process(
    setup: QueueSetup,
    runtime: AgentRuntime,
    threads: ThreadStore,
    keys: KeyServices,
    quota: QuotaService,
) -> InProcessEnqueuer:
    """Runs each turn in this process through the worker's own job (``[worker].eager``, tests),
    with the heavy tools' jobs and the follow-up turns run the same way."""
    box: dict[str, BackgroundServices] = {}

    async def run(job: TurnJob) -> None:
        await run_background_turn(job, box["services"])

    enqueuer = InProcessEnqueuer(run, setup.running)
    worker = get_worker_settings()
    follow_ups = FollowUps(threads, setup.bus, enqueuer, setup.background.running_ttl_seconds)
    lifecycle = JobLifecycle(setup.thread_bus, worker.event_ttl_seconds, follow_ups)
    jobs = _job_enqueuer(setup, threads, keys, lifecycle)
    gateway = JobGateway(threads.jobs, jobs, worker.max_open_jobs_per_user, setup.thread_bus)
    box["services"] = _background(setup, runtime, (threads, keys, quota), (gateway, follow_ups))
    return enqueuer


def _background(
    setup: QueueSetup,
    runtime: AgentRuntime,
    stores: tuple[ThreadStore, KeyServices, QuotaService],
    jobs: tuple[JobGateway, FollowUps],
) -> BackgroundServices:
    """The turn runner's collaborators for a turn run in this process."""
    threads, keys, quota = stores
    return BackgroundServices(
        threads=threads,
        bus=setup.bus,
        load_keys=lambda user_id: load_turn_keys(keys.vault, keys.operator, user_id),
        build_model=runtime.build_model,
        refund=quota.refund,
        turn_settings=runtime.turn_settings(),
        settings=replace(setup.background, max_resumes=runtime.max_resumes_per_turn),
        jobs=jobs[0],
        job_store=threads.jobs,
        thread_bus=setup.thread_bus,
        follow_ups=jobs[1],
    )


def _job_enqueuer(
    setup: QueueSetup,
    threads: ThreadStore,
    keys: KeyServices,
    lifecycle: JobLifecycle,
) -> InProcessEnqueuer[ToolJob]:
    """Runs each background tool job in this process through the tools worker's own runner."""
    services = JobServices(
        store=threads.jobs,
        runners=job_runners(),
        operator=keys.operator,
        settings=JobSettings.from_config(get_worker_settings()),
        on_job_ended=lifecycle.ended,
        on_job_started=lifecycle.started,
    )
    return InProcessEnqueuer(partial(run_background_job, services=services), setup.running)


def get_turn_queue(
    request: Request,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    threads: Annotated[ThreadStore, Depends(get_threads)],
    keys: Annotated[KeyServices, Depends(get_key_services)],
    quota: Annotated[QuotaService, Depends(get_quota)],
) -> TurnQueue:
    """The turn streams and the queue: the worker's, or this process when none is configured."""
    setup = cast(QueueSetup, request.app.state.turn_queue)
    enqueuer = setup.enqueuer or _in_process(setup, runtime, threads, keys, quota)
    return TurnQueue(setup.bus, enqueuer, setup.timing, setup.background, setup.thread_bus)


def get_client_address(request: Request) -> str:
    """The address the request came from: the socket peer, or the ``X-Forwarded-For`` entry the
    configured number of trusted proxies vouch for (none by default)."""
    hops = auth_runtime(request).settings.trusted_proxy_hops
    peer = request.client.host if request.client else None
    return client_address(peer, request.headers.get("x-forwarded-for"), hops)
