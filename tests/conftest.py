"""Fixtures shared by the whole suite."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import logfire
import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app import telemetry
from app.telemetry import scrubbing_options
from config import telemetry as telemetry_settings
from tools.emissions.inventory import clear_inventory_cache


@pytest.fixture(autouse=True)
def fresh_inventory_cache() -> Iterator[None]:
    """Each test reads its own (mocked) TRI: no inventory is reused from another test."""
    clear_inventory_cache()
    yield
    clear_inventory_cache()


@pytest.fixture(autouse=True)
def no_monitoring(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test records or exports spans unless it asks for them: the shipped monitoring settings
    load as disabled, and Logfire is told never to send, whatever token the machine has.

    A test that exercises monitoring passes its own enabled settings and configures Logfire
    with an in-memory exporter.
    """
    shipped = telemetry_settings.load_telemetry_settings

    def disabled(path: Path | None = None) -> telemetry_settings.TelemetrySettings:
        return replace(shipped(path), enabled=False)

    monkeypatch.setattr(telemetry_settings, "load_telemetry_settings", disabled)
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.setenv("LOGFIRE_IGNORE_NO_CONFIG", "1")
    for name in ("LOGFIRE_TOKEN", "LOGFIRE_READ_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    telemetry_settings.get_telemetry_settings.cache_clear()
    yield
    telemetry_settings.get_telemetry_settings.cache_clear()


@pytest.fixture
def monitoring() -> telemetry_settings.TelemetrySettings:
    """The shipped monitoring settings, switched on (the suite loads them disabled)."""
    return replace(telemetry_settings.get_telemetry_settings(), enabled=True)


@pytest.fixture
def exporter(monitoring: telemetry_settings.TelemetrySettings) -> Iterator[TestExporter]:
    """Logfire configured as the program configures it, but exporting to memory only."""
    memory = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        scrubbing=scrubbing_options(monitoring),
        additional_span_processors=[SimpleSpanProcessor(memory)],
    )
    telemetry._otel_client.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield memory
    telemetry._otel_client.cache_clear()  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests (``pytest.mark.anyio``) on asyncio only; trio is not used."""
    return "asyncio"
