"""Typed loader for the ``[mail]`` settings: where the SMTP server's configuration is found.

The server itself (host, port, encryption, login, password, sender) is configured in the
environment (``.env``), one place for Docker and native runs; this section only names the
variables, the link origin and the time limit. The values are read and checked when the web
program starts (``api.services.auth.smtp``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from config.parsing import read_toml, require_number, require_str, section, subtable
from config.telemetry import load_telemetry_settings

_NAME = "mail"
_PRODUCTION = "production"


@dataclass(frozen=True)
class SmtpVariables:
    """Names of the environment variables that configure the SMTP server.

    Attributes:
        host: The server's host name.
        port: Its port.
        security: How the connection is encrypted: ``starttls``, ``tls`` (implicit) or ``none``.
        username: The login; empty or unset when the server needs none.
        password: The password (a secret).
        from_address: The ``From`` header of every email.
    """

    host: str
    port: str
    security: str
    username: str
    password: str
    from_address: str


@dataclass(frozen=True)
class MailSettings:
    """Mail settings. No SMTP value is stored here, only the names of their variables.

    Attributes:
        variables: The environment variables that configure the SMTP server.
        app_base_url: Origin of the web app, with no path; links in emails are built from it.
        timeout_seconds: Seconds one SMTP exchange may take.
        container_loopback_host: Inside a container, the host a loopback SMTP host stands for.
    """

    variables: SmtpVariables
    app_base_url: str
    timeout_seconds: float
    container_loopback_host: str


def _variables(table: dict[str, object]) -> SmtpVariables:
    def name(key: str) -> str:
        return require_str(table, key, _NAME).strip()

    return SmtpVariables(
        host=name("host_env_var"),
        port=name("port_env_var"),
        security=name("security_env_var"),
        username=name("username_env_var"),
        password=name("password_env_var"),
        from_address=name("from_env_var"),
    )


def _loopback_host(table: dict[str, object]) -> str:
    raw = subtable(table, "container", _NAME)
    return require_str(raw, "loopback_host", f"{_NAME}.container").strip()


def _base_url(table: dict[str, object], environment: str) -> str:
    value = require_str(table, "app_base_url", _NAME).strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
        raise ValueError(f"{_NAME}.app_base_url must be an http(s) origin with no path")
    if parts.query or parts.fragment:
        raise ValueError(f"{_NAME}.app_base_url must be an http(s) origin with no path")
    if environment == _PRODUCTION and parts.scheme != "https":
        raise ValueError(
            f"{_NAME}.app_base_url must be https when telemetry.environment is production",
        )
    return value


def load_mail_settings(path: Path | None = None) -> MailSettings:
    """Load and validate the mail settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (timeout in seconds).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    environment = load_telemetry_settings(path).environment
    return MailSettings(
        variables=_variables(table),
        app_base_url=_base_url(table, environment),
        timeout_seconds=require_number(table, "timeout_seconds", minimum=0.001, name=_NAME),
        container_loopback_host=_loopback_host(table),
    )


@lru_cache(maxsize=1)
def get_mail_settings() -> MailSettings:
    """Return the cached mail settings from the default file."""
    return load_mail_settings()
