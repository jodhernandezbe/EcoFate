"""Tests for the ``[ui]`` settings loader (web backend and display settings)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from config.ui import get_ui_settings, load_ui_settings
from tests.config.graph_text import GRAPH
from tools.registry import get_all_tools

_BASE = """
[ui]
host = "127.0.0.1"
port = 9000
frontend_dist = "frontend/dist"
max_key_length = 64

[ui.container]
bind_host = "0.0.0.0"

[ui.keyring]
service = "svc"

[ui.keyring.accounts]
openai = "acct-openai"
census = "acct-census"
comptox = "acct-comptox"

[ui.prompts]
scope_classifier = "classifier"
scope_addendum = "addendum"
scope_fallback = "fallback"
history_window = 4
completion_classifier = "completion"
completion_nudge = "nudge"
max_nudges = 1

[ui.step_labels]
some_tool = "Did a thing"

[ui.map]
light_style = "https://example.test/light.json"
dark_style = "https://example.test/dark.json"
sector_half_angle_deg = 20.0
vertex_spacing_deg = 10.0
marker_min_px = 4.0
marker_max_px = 10.0
coordinate_tolerance_deg = 0.001

[ui.map.initial_view]
west = -10.0
south = 20.0
east = 10.0
north = 30.0

[ui.display]
significant_digits = 2
narrow_breakpoint_px = 800
suggestions = ["first", "second"]

[ui.layout]
rail_collapsed_px = 60
rail_default_px = 240
rail_min_px = 200
rail_max_px = 320
chat_default_share = 0.34
chat_min_px = 280
chat_max_share = 0.55
overview_default_share = 0.4
overview_min_share = 0.15
overview_max_share = 0.75

[ui.report]
title = "Title"
disclaimer = "Disclaimer"
assessor_note = "Note"
no_assessor_summary = "None available"
empty_section = "Empty"
not_reported = "absent"
file_name = "report-{cas}-{date}.docx"
brand = "Brand"
logo = "api/assets/report-logo.png"
page_label = "Page {page} of {pages}"

[ui.report.headings]
summary = "H1"
chemical = "H2"
sources = "H3"
releases = "H4"
exposure = "H5"
risk = "H6"
uncertainties = "H7"
assessor = "H8"

[ui.pricing."model-a"]
input_usd_per_mtok = 1.5
cached_input_usd_per_mtok = 0.5
output_usd_per_mtok = 3.0
priced_on = 2026-01-02
source_url = "https://example.test/pricing"
"""
UI = _BASE.replace('[ui.pricing."model-a"]', GRAPH + '\n[ui.pricing."model-a"]')


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in UI.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_ui_settings(_write(tmp_path, UI))
    assert (settings.host, settings.port, settings.origin) == (
        "127.0.0.1",
        9000,
        "http://127.0.0.1:9000",
    )
    assert settings.frontend_dist.is_absolute()
    assert settings.keyring.service == "svc"
    assert dict(settings.keyring.accounts) == {
        "openai": "acct-openai",
        "census": "acct-census",
        "comptox": "acct-comptox",
    }
    assert settings.prompts.history_window == 4
    assert (settings.prompts.completion, settings.prompts.nudge) == ("completion", "nudge")
    assert settings.prompts.max_nudges == 1
    assert dict(settings.step_labels) == {"some_tool": "Did a thing"}
    assert settings.map.sector_half_angle_deg == 20.0
    assert settings.map.vertex_spacing_deg == 10.0
    view = settings.map.initial_view
    assert (view.west, view.south, view.east, view.north) == (-10.0, 20.0, 10.0, 30.0)
    assert settings.display.suggestions == ("first", "second")
    assert (settings.layout.rail.collapsed_px, settings.layout.chat.min_px) == (60, 280)
    assert settings.layout.overview.default_share == 0.4
    price = settings.pricing["model-a"]
    assert (price.input_usd_per_mtok, price.priced_on) == (1.5, date(2026, 1, 2))


def test_shipped_settings_load() -> None:
    settings = get_ui_settings()
    assert settings.keyring.service == "epa-chemical-risk-agent"
    assert dict(settings.keyring.accounts) == {
        "openai": "openai_api_key",
        "census": "census_api_key",
        "comptox": "comptox_api_key",
    }
    assert 3 <= len(settings.display.suggestions) <= 4


def test_shipped_price_of_the_configured_model_is_sourced() -> None:
    price = get_ui_settings().pricing["gpt-4.1"]
    assert (price.input_usd_per_mtok, price.output_usd_per_mtok) == (2.0, 8.0)
    assert 0 < price.cached_input_usd_per_mtok < price.input_usd_per_mtok
    assert price.source_url.startswith("https://platform.openai.com/")
    assert price.priced_on == date(2026, 10, 20)


def test_shipped_step_labels_name_registered_tools() -> None:
    registered = {tool.name for tool in get_all_tools()}
    assert set(get_ui_settings().step_labels) == registered


def test_container_bind_host(tmp_path: Path) -> None:
    assert load_ui_settings(_write(tmp_path, UI)).container_bind_host == "0.0.0.0"
    path = _replace(tmp_path, "bind_host", 'bind_host = "127.0.0.1"')
    assert load_ui_settings(path).container_bind_host == "127.0.0.1"


def test_shipped_container_bind_host() -> None:
    assert get_ui_settings().container_bind_host == "0.0.0.0"


def test_localhost_accepted(tmp_path: Path) -> None:
    path = _replace(tmp_path, "host", 'host = "localhost"')
    assert load_ui_settings(path).host == "localhost"


def test_unpriced_when_pricing_empty(tmp_path: Path) -> None:
    text = UI.split('[ui.pricing."model-a"]')[0] + "[ui.pricing]\n"
    assert dict(load_ui_settings(_write(tmp_path, text)).pricing) == {}


@pytest.mark.parametrize(
    ("line_start", "new_line", "key"),
    [
        ("host", 'host = "0.0.0.0"', "ui.host"),
        ("host", 'host = "example.com"', "ui.host"),
        ("bind_host", 'bind_host = "203.0.113.5"', "ui.container.bind_host"),
        ("bind_host", 'bind_host = ""', "ui.container.bind_host"),
        ("bind_host", "bind_host = 8", "ui.container.bind_host"),
        ("bind_host", 'bind_host = "example.com"', "ui.container.bind_host"),
        ("port", "port = 0", "ui.port"),
        ("port", "port = 70000", "ui.port"),
        ("port", "port = true", "ui.port"),
        ("max_key_length", "max_key_length = 0", "ui.max_key_length"),
        ("service", 'service = " "', "ui.keyring.service"),
        ("census", 'census = ""', "ui.keyring.accounts.census"),
        ("comptox", 'comptox = "acct-openai"', "own account name"),
        ("openai", "openai = 5", "ui.keyring.accounts.openai"),
        ("scope_classifier", 'scope_classifier = ""', "ui.prompts.scope_classifier"),
        ("history_window", "history_window = -1", "ui.prompts.history_window"),
        ("completion_classifier", 'completion_classifier = ""', "ui.prompts.completion_classifier"),
        ("completion_nudge", "", "ui.prompts.completion_nudge"),
        ("max_nudges", "max_nudges = -1", "ui.prompts.max_nudges"),
        ("max_nudges", "max_nudges = true", "ui.prompts.max_nudges"),
        ("some_tool", "some_tool = 3", "ui.step_labels.some_tool"),
        ("sector_half_angle_deg", "sector_half_angle_deg = 90", "sector_half_angle_deg"),
        ("vertex_spacing_deg", "vertex_spacing_deg = 0.01", "ui.map.vertex_spacing_deg"),
        ("vertex_spacing_deg", "vertex_spacing_deg = 91", "vertex_spacing_deg"),
        ("west", "west = 10.0", "west < east"),
        ("north", "north = 20.0", "south < north"),
        ("north", "north = 91.0", "ui.map.initial_view.north"),
        ("west", "west = -181.0", "ui.map.initial_view.west"),
        ("south", "south = true", "ui.map.initial_view.south"),
        ("marker_max_px", "marker_max_px = 1.0", "ui.map.marker_max_px"),
        ("coordinate_tolerance_deg", "coordinate_tolerance_deg = -1", "coordinate_tolerance"),
        ("significant_digits", "significant_digits = 0", "ui.display.significant_digits"),
        ("suggestions", "suggestions = []", "ui.display.suggestions"),
        ("rail_min_px", "rail_min_px = 300", "ui.layout.rail"),
        ("rail_collapsed_px", "rail_collapsed_px = 200", "rail_collapsed_px"),
        ("rail_max_px", "rail_max_px = 1.5", "ui.layout.rail_max_px"),
        ("rail_default_px", "rail_default_px = true", "ui.layout.rail_default_px"),
        ("chat_min_px", "chat_min_px = 0", "ui.layout.chat_min_px"),
        ("chat_max_share", "chat_max_share = 1", "ui.layout.chat_max_share"),
        ("chat_default_share", "chat_default_share = 0.6", "chat_default_share"),
        ("overview_min_share", "overview_min_share = 0.5", "ui.layout.overview"),
        ("overview_max_share", "overview_max_share = 0", "ui.layout.overview_max_share"),
        ("input_usd_per_mtok", "input_usd_per_mtok = -1", "input_usd_per_mtok"),
        ("output_usd_per_mtok", "output_usd_per_mtok = true", "output_usd_per_mtok"),
        ("cached_input_usd_per_mtok", 'cached_input_usd_per_mtok = "1"', "cached_input"),
        ("priced_on", 'priced_on = "2026-01-02"', "priced_on"),
        ("source_url", 'source_url = ""', "source_url"),
    ],
)
def test_invalid_entry(tmp_path: Path, line_start: str, new_line: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_ui_settings(_replace(tmp_path, line_start, new_line))


@pytest.mark.parametrize("old", ["max_threads = 5\n", "[ui.threads]\nmax_retained = 5\n"])
def test_removed_thread_limit_is_rejected(tmp_path: Path, old: str) -> None:
    text = UI.replace("[ui.report]", "[ui.report]", 1)
    if old.startswith("max_threads"):
        text = text.replace("max_key_length = 64\n", "max_key_length = 64\n" + old, 1)
    else:
        text = text.replace("[ui.report]", old + "\n[ui.report]", 1)
    with pytest.raises(ValueError, match=r"database\.thread_retention_days"):
        load_ui_settings(_write(tmp_path, text))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ui section is missing"):
        load_ui_settings(_write(tmp_path, "[agent]\n"))
