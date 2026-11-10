"""The SMTP server read from the environment: every value checked, the variable named."""

from __future__ import annotations

import pytest

from api.services.auth.smtp import MailSetupError, Security, SmtpServer, smtp_server
from config.mail import get_mail_settings

SETTINGS = get_mail_settings()
NAMES = SETTINGS.variables
GOOD = {
    NAMES.host: "smtp.example.com",
    NAMES.port: "587",
    NAMES.security: "starttls",
    NAMES.username: "mailer",
    NAMES.from_address: "EcoFate <no-reply@example.com>",
}


def _with(**changes: str | None) -> dict[str, str]:
    environ = dict(GOOD)
    for key, value in changes.items():
        name = getattr(NAMES, key)
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value
    return environ


def test_a_complete_environment_gives_the_server() -> None:
    assert smtp_server(GOOD, SETTINGS, container=False) == SmtpServer(
        "smtp.example.com",
        587,
        Security.STARTTLS,
        "mailer",
        "EcoFate <no-reply@example.com>",
    )


def test_the_login_is_optional() -> None:
    assert smtp_server(_with(username=None), SETTINGS, container=False).username == ""
    assert smtp_server(_with(username=""), SETTINGS, container=False).username == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("starttls", Security.STARTTLS),
        ("TLS", Security.TLS),
        ("None", Security.NONE),
    ],
)
def test_the_security_level_is_one_of_three_in_any_case(value: str, expected: Security) -> None:
    server = smtp_server(_with(security=value, username=""), SETTINGS, container=False)
    assert server.security is expected


def test_implicit_tls_on_465_with_a_login_is_accepted() -> None:
    cloudflare = _with(
        host="smtp.mx.cloudflare.net",
        port="465",
        security="tls",
        username="api_token",
    )
    server = smtp_server(cloudflare, SETTINGS, container=False)
    assert (server.port, server.security, server.username) == (465, Security.TLS, "api_token")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("host", None),
        ("host", "  "),
        ("host", "smtp example.com"),
        ("port", None),
        ("port", "smtp"),
        ("port", "0"),
        ("port", "70000"),
        ("port", "-25"),
        ("security", None),
        ("security", "true"),
        ("security", "ssl3"),
        ("from_address", None),
        ("from_address", "nobody"),
        ("from_address", "a@example.com\nBcc: victim@example.com"),
    ],
)
def test_a_missing_or_bad_value_stops_start_up_naming_the_variable(
    key: str,
    value: str | None,
) -> None:
    with pytest.raises(MailSetupError) as raised:
        smtp_server(_with(**{key: value}), SETTINGS, container=False)
    assert getattr(NAMES, key) in str(raised.value)
    if value and value.strip():
        assert value not in str(raised.value)  # the value itself is never shown


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1"])
def test_in_a_container_a_loopback_host_means_the_mail_service(host: str) -> None:
    server = smtp_server(_with(host=host), SETTINGS, container=True)
    assert server.host == SETTINGS.container_loopback_host
    assert smtp_server(_with(host=host), SETTINGS, container=False).host == host


def test_in_a_container_a_real_host_is_used_as_written() -> None:
    server = smtp_server(_with(host="smtp.example.com"), SETTINGS, container=True)
    assert server.host == "smtp.example.com"


def test_the_password_is_not_part_of_the_server() -> None:
    environ = _with() | {NAMES.password: "smtp-secret-value"}  # pragma: allowlist secret
    assert "smtp-secret-value" not in repr(smtp_server(environ, SETTINGS, container=False))


def test_a_login_to_a_remote_server_must_be_encrypted() -> None:
    with pytest.raises(MailSetupError) as raised:
        smtp_server(_with(security="none"), SETTINGS, container=False)
    assert NAMES.security in str(raised.value)
    assert smtp_server(_with(security="none", username=""), SETTINGS, container=False)


@pytest.mark.parametrize(("host", "container"), [("127.0.0.1", False), ("localhost", True)])
def test_a_local_mail_catcher_may_take_a_login_without_tls(host: str, container: bool) -> None:
    server = smtp_server(_with(host=host, security="none"), SETTINGS, container=container)
    assert server.username == "mailer" and server.security is Security.NONE


def test_outside_a_container_the_mail_catchers_name_is_not_trusted_as_local() -> None:
    catcher = _with(host=SETTINGS.container_loopback_host, security="none")
    with pytest.raises(MailSetupError):
        smtp_server(catcher, SETTINGS, container=False)
    assert smtp_server(catcher, SETTINGS, container=True).security is Security.NONE
