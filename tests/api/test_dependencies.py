"""The runtime the web program runs with is built from configuration."""

from __future__ import annotations

from api.dependencies import get_runtime
from config.population import get_population_settings
from config.risk_bands import get_risk_bands
from config.telemetry import get_telemetry_settings
from config.ui import get_ui_settings


def test_the_workspace_rules_come_from_settings() -> None:
    rules = get_runtime().workspace_rules
    assert rules is not None
    assert rules.thresholds == get_risk_bands()
    assert rules.coordinate_tolerance_deg == get_ui_settings().map.coordinate_tolerance_deg
    assert rules.default_radius_km == get_population_settings().default_radius_km


def test_each_turn_is_recorded_with_the_monitoring_settings() -> None:
    assert get_runtime().telemetry == get_telemetry_settings()
