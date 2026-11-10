"""Sending account email: the message, the SMTP exchange and failures that never escape."""

from __future__ import annotations

import logging
import smtplib
from typing import Any

import pytest

from api.services.auth.email_address import InvalidEmailError, normalise_email
from api.services.auth.mailer import Mail, SmtpMailer, deliver
from api.services.auth.messages import (
    existing_account_mail,
    fragment_link,
    reset_mail,
    verification_mail,
)
from api.services.auth.smtp import Security, SmtpServer
from config.mail import get_mail_settings
from tests.fakes_accounts import RecordingMailer

pytestmark = pytest.mark.anyio
BASE = "http://127.0.0.1:8000"


def test_links_carry_the_token_in_the_fragment_never_the_query() -> None:
    link = fragment_link(BASE, "reset", "tok-123")
    assert link == f"{BASE}/#reset=tok-123" and "?" not in link
    assert "#verify=tok" in verification_mail("a@example.com", BASE, "tok").body
    assert "#reset=tok" in reset_mail("a@example.com", BASE, "tok").body


def test_the_existing_account_mail_has_no_token_and_no_link_to_act_on() -> None:
    mail = existing_account_mail("a@example.com", BASE)
    assert "#" not in mail.body and mail.to == "a@example.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Ana@EXAMPLE.Com ", "Ana@example.com"),
        ("a.b+c@sub.Example.org", "a.b+c@sub.example.org"),
    ],
)
def test_an_address_is_trimmed_with_the_domain_lower_cased(raw: str, expected: str) -> None:
    assert normalise_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "nobody",
        "a@",
        "@b.test",
        "a b@c.test",
        "a@b",
        "a@b.test\nBcc: x@y.test",
        "x" * 250 + "@b.test",
    ],
)
def test_a_bad_address_is_refused(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalise_email(raw)


class _FakeSmtp:
    instances: list[_FakeSmtp] = []

    def __init__(self, host: str, port: int, timeout: float, context: object = None) -> None:
        self.args = (host, port, timeout)
        self.context = context
        self.closed = False
        self.actions: list[str] = []
        self.sent: Any = None
        _FakeSmtp.instances.append(self)

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self, context: object) -> None:
        self.actions.append("starttls")
        if getattr(self, "refuse_tls", False):
            raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")

    def close(self) -> None:
        self.closed = True

    def login(self, user: str, password: str) -> None:
        self.actions.append(f"login:{user}")

    def send_message(self, message: Any) -> None:
        self.sent = message
        self.actions.append("send")


async def test_the_smtp_mailer_uses_the_configured_server_login_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeSmtp.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    settings = get_mail_settings()
    server = SmtpServer(
        "smtp.example.com",
        587,
        Security.STARTTLS,
        "mailer",
        "EcoFate <no-reply@example.com>",
    )
    mailer = SmtpMailer(server, settings, {settings.variables.password: "secret"})
    await mailer.send(Mail("a@example.com", "Subject", "Body"))
    (smtp,) = _FakeSmtp.instances
    assert smtp.args == ("smtp.example.com", 587, settings.timeout_seconds)
    assert smtp.actions == ["starttls", "login:mailer", "send"]
    assert smtp.sent["To"] == "a@example.com" and smtp.sent["From"] == server.from_address


async def test_no_login_is_attempted_without_a_username(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSmtp.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    server = SmtpServer("127.0.0.1", 1025, Security.NONE, "", "EcoFate <no-reply@example.com>")
    await SmtpMailer(server, get_mail_settings(), {}).send(Mail("a@example.com", "S", "B"))
    assert _FakeSmtp.instances[0].actions == ["send"]


async def test_a_failure_while_delivering_is_logged_by_class_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mailer = RecordingMailer(fail=smtplib.SMTPServerDisconnected("secret@host token-abc"))
    with caplog.at_level(logging.WARNING):
        await deliver(mailer, Mail("a@example.com", "S", "link #reset=token-abc"))
    assert "SMTPServerDisconnected" in caplog.text
    assert "token-abc" not in caplog.text and "a@example.com" not in caplog.text


async def test_an_unexpected_error_is_not_swallowed() -> None:
    with pytest.raises(RuntimeError):
        await deliver(RecordingMailer(fail=RuntimeError("bug")), Mail("a@example.com", "S", "B"))


async def test_implicit_tls_connects_encrypted_from_the_start_and_verifies_the_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssl

    _FakeSmtp.instances = []
    plain: list[object] = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSmtp)

    def no_plain_connection(*args: object, **kwargs: object) -> None:
        plain.append(args)

    monkeypatch.setattr(smtplib, "SMTP", no_plain_connection)
    settings = get_mail_settings()
    server = SmtpServer(
        "smtp.mx.cloudflare.net",
        465,
        Security.TLS,
        "api_token",
        "EcoFate <no-reply@example.com>",
    )
    mailer = SmtpMailer(server, settings, {settings.variables.password: "cf-token"})
    await mailer.send(Mail("a@example.com", "S", "B"))
    (smtp,) = _FakeSmtp.instances
    assert plain == []  # never a plain connection first
    assert smtp.args == ("smtp.mx.cloudflare.net", 465, settings.timeout_seconds)
    assert isinstance(smtp.context, ssl.SSLContext)
    assert smtp.context.verify_mode is ssl.CERT_REQUIRED and smtp.context.check_hostname
    assert smtp.actions == ["login:api_token", "send"]  # no STARTTLS on top of TLS


async def test_a_server_that_refuses_starttls_is_closed_and_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Refusing(_FakeSmtp):
        refuse_tls = True

    Refusing.instances = []
    _FakeSmtp.instances = []
    monkeypatch.setattr(smtplib, "SMTP", Refusing)
    server = SmtpServer(
        "smtp.example.com",
        587,
        Security.STARTTLS,
        "mailer",
        "EcoFate <no-reply@example.com>",
    )
    mailer = SmtpMailer(server, get_mail_settings(), {})
    with pytest.raises(smtplib.SMTPNotSupportedError):
        await mailer.send(Mail("a@example.com", "S", "B"))
    (smtp,) = _FakeSmtp.instances
    assert smtp.closed and "send" not in smtp.actions and "login:mailer" not in smtp.actions
