"""Tests for the ``[auth]`` settings loader (accounts, sessions, throttling, Argon2id)."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.auth import get_auth_settings, load_auth_settings

AUTH_FILE = """
[telemetry]
enabled = false
service_name = "svc"
environment = "test"
console = false
write_token_env_var = "W"  # pragma: allowlist secret
read_token_env_var = "R"  # pragma: allowlist secret
query_timeout_seconds = 5.0
session_window_hours = 24
max_sessions = 10
max_rows = 100
trace_url_template = "https://x.test/{trace_id}"

[telemetry.spans]
cli_session = "cli run"
web_turn = "web turn"
web_enqueue = "web enqueue"

[telemetry.attributes]
session_id = "session.id"
question = "q"
model = "m"
outcome = "o"
usage_prefix = "u."
session_usage_prefix = "s."
turn_id = "t"
resume_index = "r"
user_id = "enduser.id"
queue_wait_seconds = "w"

[telemetry.bridge]
operation = "op"
model_operation = "chat"
tool_operation = "tool_run"
tool_name = "tn"
usage_metadata = "um"

[auth]
signup_open = true
password_min_length = 12
password_max_length = 128
session_idle_minutes = 60
session_absolute_days = 2
verification_token_hours = 24
reset_token_minutes = 30
cookie_name = "sid"
cookie_secure = true
trusted_proxy_hops = 1
session_secret_env_var = "TEST_SESSION_SECRET"  # pragma: allowlist secret

[auth.argon2]
time_cost = 2
memory_cost_kib = 1024
parallelism = 2

[auth.throttle]
attempts = 4
window_minutes = 10
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in AUTH_FILE.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_auth_settings(_write(tmp_path, AUTH_FILE))
    assert settings.signup_open is True
    assert (settings.password_min_length, settings.password_max_length) == (12, 128)
    assert (settings.session_idle_minutes, settings.session_absolute_days) == (60, 2)
    assert (settings.verification_token_hours, settings.reset_token_minutes) == (24, 30)
    assert (settings.cookie_name, settings.cookie_secure) == ("sid", True)
    assert settings.trusted_proxy_hops == 1
    assert settings.session_secret_env_var == "TEST_SESSION_SECRET"  # pragma: allowlist secret
    assert (settings.argon2.time_cost, settings.argon2.memory_cost_kib) == (2, 1024)
    assert settings.argon2.parallelism == 2
    assert (settings.throttle.attempts, settings.throttle.window_minutes) == (4, 10)


def test_lifetimes_in_seconds(tmp_path: Path) -> None:
    settings = load_auth_settings(_write(tmp_path, AUTH_FILE))
    assert settings.session_idle_seconds == 3600
    assert settings.session_absolute_seconds == 2 * 86400
    assert settings.throttle.window_seconds == 600


def test_shipped_settings_load_without_a_secret() -> None:
    settings = get_auth_settings()
    assert settings.session_secret_env_var == "ECOFATE_SESSION_SECRET"  # pragma: allowlist secret
    assert settings.password_min_length >= 12
    assert settings.argon2.memory_cost_kib >= 8 * settings.argon2.parallelism


@pytest.mark.parametrize(
    ("line_start", "new_line", "key"),
    [
        ("signup_open", 'signup_open = "yes"', "auth.signup_open"),
        ("signup_open", "signup_open = 1", "auth.signup_open"),
        ("password_min_length", "password_min_length = 0", "auth.password_min_length"),
        ("password_max_length", "password_max_length = true", "auth.password_max_length"),
        ("password_min_length", "password_min_length = 200", "password_min_length"),
        ("session_idle_minutes", "session_idle_minutes = 0", "auth.session_idle_minutes"),
        ("session_idle_minutes", "session_idle_minutes = -5", "auth.session_idle_minutes"),
        ("session_absolute_days", "session_absolute_days = 0", "auth.session_absolute_days"),
        ("session_absolute_days", "session_absolute_days = 1.5", "auth.session_absolute_days"),
        (
            "verification_token_hours",
            "verification_token_hours = 0",
            "auth.verification_token_hours",
        ),
        ("reset_token_minutes", "reset_token_minutes = -1", "auth.reset_token_minutes"),
        ("cookie_name", 'cookie_name = " "', "auth.cookie_name"),
        ("cookie_secure", 'cookie_secure = "no"', "auth.cookie_secure"),
        ("trusted_proxy_hops", "trusted_proxy_hops = -1", "auth.trusted_proxy_hops"),
        ("trusted_proxy_hops", "trusted_proxy_hops = true", "auth.trusted_proxy_hops"),
        ("session_secret_env_var", "session_secret_env_var = 3", "auth.session_secret_env_var"),
        ("time_cost", "time_cost = 0", "auth.argon2.time_cost"),
        ("memory_cost_kib", "memory_cost_kib = 4", "auth.argon2.memory_cost_kib"),
        ("memory_cost_kib", "memory_cost_kib = 8", "auth.argon2.memory_cost_kib"),
        ("parallelism", "parallelism = 0", "auth.argon2.parallelism"),
        ("attempts", "attempts = 0", "auth.throttle.attempts"),
        ("window_minutes", "window_minutes = 0", "auth.throttle.window_minutes"),
    ],
)
def test_invalid_value_names_the_key(
    tmp_path: Path,
    line_start: str,
    new_line: str,
    key: str,
) -> None:
    with pytest.raises(ValueError, match=key):
        load_auth_settings(_replace(tmp_path, line_start, new_line))


def test_insecure_cookie_is_refused_in_production(tmp_path: Path) -> None:
    text = AUTH_FILE.replace('environment = "test"', 'environment = "production"')
    text = text.replace("cookie_secure = true", "cookie_secure = false")
    with pytest.raises(ValueError, match="cookie_secure"):
        load_auth_settings(_write(tmp_path, text))


def test_insecure_cookie_is_allowed_outside_production(tmp_path: Path) -> None:
    text = AUTH_FILE.replace("cookie_secure = true", "cookie_secure = false")
    assert load_auth_settings(_write(tmp_path, text)).cookie_secure is False


def test_secure_cookie_is_allowed_in_production(tmp_path: Path) -> None:
    text = AUTH_FILE.replace('environment = "test"', 'environment = "production"')
    assert load_auth_settings(_write(tmp_path, text)).cookie_secure is True


@pytest.mark.parametrize("missing", ["[auth]", "[auth.argon2]", "[auth.throttle]"])
def test_missing_section(tmp_path: Path, missing: str) -> None:
    text = AUTH_FILE.replace(missing, "[other]")
    with pytest.raises(ValueError, match="auth"):
        load_auth_settings(_write(tmp_path, text))
