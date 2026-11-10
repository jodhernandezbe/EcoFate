"""Outgoing account email over SMTP, sent after the response so its latency is not observable.

Sending never raises into a request: a failure is logged by exception class only (the log never
holds an address, a link or a token) and the person simply gets no mail, which is what an
unknown address gets too.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from api.services.auth.smtp import Security, SmtpServer
from config.mail import MailSettings

logger = logging.getLogger(__name__)
MAIL_ERRORS: tuple[type[Exception], ...] = (OSError, smtplib.SMTPException, ssl.SSLError)


@dataclass(frozen=True)
class Mail:
    """One message: plain text, to one validated address.

    Attributes:
        to: The recipient (already validated, so it holds no line break).
        subject: The fixed subject.
        body: The plain-text body.
    """

    to: str
    subject: str
    body: str


class Mailer(Protocol):
    """Sends a message; tests use a recording fake."""

    async def send(self, mail: Mail) -> None:
        """Deliver ``mail``; raises one of ``MAIL_ERRORS`` when it cannot."""
        ...


class SmtpMailer:
    """Delivers through the configured SMTP server, in a worker thread, within its timeout.

    Args:
        server: Host, port, STARTTLS, login and sender (from the environment).
        settings: The time limit and the name of the password's variable.
        environ: Where the SMTP password is looked up when a message is sent.
    """

    def __init__(
        self,
        server: SmtpServer,
        settings: MailSettings,
        environ: Mapping[str, str],
    ) -> None:
        self._server = server
        self._settings = settings
        self._environ = environ

    async def send(self, mail: Mail) -> None:
        """Deliver ``mail`` (see ``Mailer``)."""
        await asyncio.to_thread(self._send, mail)

    def _message(self, mail: Mail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._server.from_address
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message.set_content(mail.body)
        return message

    def _connect(self) -> smtplib.SMTP:
        """A connection, encrypted as configured (certificates verified for TLS and STARTTLS)."""
        server, timeout = self._server, self._settings.timeout_seconds
        if server.security is Security.TLS:
            context = ssl.create_default_context()
            return smtplib.SMTP_SSL(server.host, server.port, timeout=timeout, context=context)
        smtp = smtplib.SMTP(server.host, server.port, timeout=timeout)
        if server.security is Security.STARTTLS:
            try:
                smtp.starttls(context=ssl.create_default_context())
            except BaseException:
                smtp.close()  # never leave a half-open connection behind
                raise
        return smtp

    def _send(self, mail: Mail) -> None:
        with self._connect() as smtp:
            password = self._environ.get(self._settings.variables.password, "")
            if self._server.username and password:
                smtp.login(self._server.username, password)
            smtp.send_message(self._message(mail))


async def deliver(mailer: Mailer, mail: Mail) -> None:
    """Send ``mail`` as a background task: a failure is logged by class and swallowed."""
    try:
        await mailer.send(mail)
    except MAIL_ERRORS as error:
        logger.warning("Account email was not sent: %s", type(error).__name__)
