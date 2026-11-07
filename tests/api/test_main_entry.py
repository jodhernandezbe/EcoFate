"""Tests for the launch command: loopback only, and a clear message without a built frontend."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI

import api.__main__ as entry
from api.main import create_app
from config.telemetry import TelemetrySettings
from config.ui import UiSettings, get_ui_settings


def _capture_launch(monkeypatch: pytest.MonkeyPatch, settings: UiSettings) -> dict[str, object]:
    """Replace the settings and ``uvicorn.run``; the returned dict fills when a server starts."""
    launched: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        launched.update(kwargs)

    monkeypatch.setattr(entry, "ui_settings", lambda: settings)
    monkeypatch.setattr(entry.uvicorn, "run", fake_run)
    return launched


def test_missing_frontend_exits_with_the_build_command(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        entry.require_built_frontend(tmp_path / "dist")
    assert "npm --prefix frontend run build" in str(info.value)


def test_built_frontend_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    entry.require_built_frontend(tmp_path)


def test_main_serves_on_the_configured_loopback_address(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    settings = replace(get_ui_settings(), frontend_dist=tmp_path)
    launched = _capture_launch(monkeypatch, settings)
    entry.main()
    assert (launched["host"], launched["port"]) == (settings.host, settings.port)
    assert launched["host"] == "127.0.0.1"
    assert launched["log_config"]


def test_main_loads_the_dotenv_file_before_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    settings = replace(get_ui_settings(), frontend_dist=tmp_path)
    _capture_launch(monkeypatch, settings)
    loaded: list[bool] = []
    monkeypatch.setattr(entry, "load_dotenv", lambda: loaded.append(True) or True)
    entry.main()
    assert loaded == [True]


def test_main_does_not_start_without_a_frontend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(get_ui_settings(), frontend_dist=tmp_path / "missing")
    launched = _capture_launch(monkeypatch, settings)
    with pytest.raises(SystemExit):
        entry.main()
    assert launched == {}


def test_main_configures_monitoring_after_the_dotenv_file_and_before_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    order: list[str] = []
    settings = replace(get_ui_settings(), frontend_dist=tmp_path)

    def configure(monitoring: TelemetrySettings) -> None:
        order.append("monitoring")

    def serve(app: object, **kwargs: object) -> None:
        order.append("serve")

    monkeypatch.setattr(entry, "ui_settings", lambda: settings)
    monkeypatch.setattr(entry, "load_dotenv", lambda: order.append("env") or True)
    monkeypatch.setattr(entry, "configure_telemetry", configure)
    monkeypatch.setattr(entry.uvicorn, "run", serve)
    entry.main()
    assert order == ["env", "monitoring", "serve"]


def test_container_flag_binds_the_container_address(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    settings = replace(get_ui_settings(), frontend_dist=tmp_path, container_bind_host="0.0.0.0")
    launched = _capture_launch(monkeypatch, settings)
    entry.main(["--container"])
    assert (launched["host"], launched["port"]) == ("0.0.0.0", settings.port)


def test_unknown_argument_exits_without_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    settings = replace(get_ui_settings(), frontend_dist=tmp_path)
    launched = _capture_launch(monkeypatch, settings)
    with pytest.raises(SystemExit):
        entry.main(["--host", "0.0.0.0"])
    assert launched == {}


@pytest.mark.parametrize("argv", [[], ["--container"]])
def test_origin_guard_uses_the_configured_origin_in_both_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    settings = replace(get_ui_settings(), frontend_dist=tmp_path)
    launched = _capture_launch(monkeypatch, settings)
    built: list[tuple[str, bool]] = []

    def build(ui: UiSettings, *, keys_from_environment: bool = False) -> FastAPI:
        built.append((ui.origin, keys_from_environment))
        return create_app(ui, keys_from_environment=keys_from_environment)

    monkeypatch.setattr(entry, "create_app", build)
    entry.main(argv)
    # The origin is [ui].host:[ui].port in both modes; only the container reads keys from .env.
    assert built == [(f"http://{settings.host}:{settings.port}", argv == ["--container"])]
    assert launched["port"] == settings.port
