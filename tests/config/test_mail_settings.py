"""Tests for the ``[mail]`` settings loader: variable names, link origin, time limit."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.mail import get_mail_settings, load_mail_settings
from tests.config.test_auth_settings import AUTH_FILE as _TELEMETRY_AND_AUTH

_MAIL = """
[mail]
host_env_var = "T_HOST"
port_env_var = "T_PORT"
security_env_var = "T_SEC"
username_env_var = "T_USER"
password_env_var = "T_PASS"  # pragma: allowlist secret
from_env_var = "T_FROM"
app_base_url = "https://app.example.test"
timeout_seconds = 7.5

[mail.container]
loopback_host = "mail-service"
"""
_FILE = _TELEMETRY_AND_AUTH + _MAIL


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in _FILE.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_mail_settings(_write(tmp_path, _FILE))
    names = settings.variables
    assert (names.host, names.port, names.security) == ("T_HOST", "T_PORT", "T_SEC")
    assert (names.username, names.from_address) == ("T_USER", "T_FROM")
    assert names.password == "T_PASS"  # pragma: allowlist secret
    assert settings.app_base_url == "https://app.example.test"
    assert settings.timeout_seconds == 7.5
    assert settings.container_loopback_host == "mail-service"


def test_trailing_slash_is_dropped(tmp_path: Path) -> None:
    path = _replace(tmp_path, "app_base_url", 'app_base_url = "https://app.example.test/"')
    assert load_mail_settings(path).app_base_url == "https://app.example.test"


def test_shipped_settings_name_variables_and_hold_no_server() -> None:
    settings = get_mail_settings()
    assert settings.variables.host == "SMTP_HOST"
    assert settings.variables.password == "SMTP_PASSWORD"  # pragma: allowlist secret
    assert settings.container_loopback_host == "mailpit"
    assert settings.app_base_url.startswith(("http://", "https://"))


@pytest.mark.parametrize(
    ("line_start", "new_line", "key"),
    [
        ("host_env_var", 'host_env_var = ""', "mail.host_env_var"),
        ("port_env_var", "port_env_var = 25", "mail.port_env_var"),
        ("security_env_var", "security_env_var = true", "mail.security_env_var"),
        ("username_env_var", 'username_env_var = " "', "mail.username_env_var"),
        ("password_env_var", 'password_env_var = ""', "mail.password_env_var"),
        ("from_env_var", "from_env_var = 1", "mail.from_env_var"),
        ("app_base_url", 'app_base_url = "ftp://x.test"', "mail.app_base_url"),
        ("app_base_url", 'app_base_url = "https://x.test/app"', "mail.app_base_url"),
        ("app_base_url", 'app_base_url = "https://x.test/#frag"', "mail.app_base_url"),
        ("app_base_url", 'app_base_url = "x.test"', "mail.app_base_url"),
        ("timeout_seconds", "timeout_seconds = 0", "mail.timeout_seconds"),
        ("timeout_seconds", "timeout_seconds = true", "mail.timeout_seconds"),
        ("loopback_host", 'loopback_host = ""', "mail.container.loopback_host"),
    ],
)
def test_invalid_value_names_the_key(
    tmp_path: Path,
    line_start: str,
    new_line: str,
    key: str,
) -> None:
    with pytest.raises(ValueError, match=key):
        load_mail_settings(_replace(tmp_path, line_start, new_line))


def test_plain_http_base_url_is_refused_in_production(tmp_path: Path) -> None:
    text = _FILE.replace('environment = "test"', 'environment = "production"')
    text = text.replace("https://app.example.test", "http://app.example.test")
    with pytest.raises(ValueError, match="app_base_url"):
        load_mail_settings(_write(tmp_path, text))


@pytest.mark.parametrize("section", ["[mail]", "[mail.container]"])
def test_missing_section(tmp_path: Path, section: str) -> None:
    with pytest.raises(ValueError, match="mail"):
        load_mail_settings(_write(tmp_path, _FILE.replace(section, "[other]")))
