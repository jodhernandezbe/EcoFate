"""The SMTP server, read from the environment once at start-up and checked there.

Every value comes from the variables ``[mail]`` names (``.env`` in practice). A missing or
malformed value stops the web program with a message that names the variable and never shows
a value. The password is not read here: the mailer reads it when it sends.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from email.utils import parseaddr
from enum import StrEnum

from config.mail import MailSettings

_MAX_PORT = 65535
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class Security(StrEnum):
    """How the SMTP connection is encrypted."""

    STARTTLS = "starttls"  # plain connection upgraded with STARTTLS (usually port 587)
    TLS = "tls"  # implicit TLS from the first byte (usually port 465)
    NONE = "none"  # no encryption: a local mail catcher only


class MailSetupError(RuntimeError):
    """The SMTP configuration in the environment is missing or invalid; safe to show."""


@dataclass(frozen=True)
class SmtpServer:
    """Where and how account emails are sent.

    Attributes:
        host: The server's host name.
        port: Its port.
        security: How the connection is encrypted.
        username: The login; empty when the server needs none.
        from_address: The ``From`` header of every email.
    """

    host: str
    port: int
    security: Security
    username: str
    from_address: str


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise MailSetupError(f"Set {name} in .env (see .env.example): the SMTP server needs it.")
    return value


def _port(environ: Mapping[str, str], name: str) -> int:
    text = _required(environ, name)
    if not text.isdigit() or not 1 <= int(text) <= _MAX_PORT:
        raise MailSetupError(f"{name} must be a port number between 1 and {_MAX_PORT}.")
    return int(text)


def _security(environ: Mapping[str, str], name: str) -> Security:
    text = _required(environ, name).lower()
    try:
        return Security(text)
    except ValueError:
        choices = ", ".join(level.value for level in Security)
        raise MailSetupError(f"{name} must be one of: {choices}.") from None


def _sender(environ: Mapping[str, str], name: str) -> str:
    text = _required(environ, name)
    if "\n" in text or "\r" in text or "@" not in parseaddr(text)[1]:
        raise MailSetupError(f"{name} must be an email address, optionally with a name.")
    return text


def _host(environ: Mapping[str, str], name: str, settings: MailSettings, container: bool) -> str:
    host = _required(environ, name)
    if any(character.isspace() for character in host):
        raise MailSetupError(f"{name} must be a host name.")
    if container and host.lower() in _LOOPBACK:  # the container itself: Mailpit is meant
        return settings.container_loopback_host
    return host


def smtp_server(
    environ: Mapping[str, str],
    settings: MailSettings,
    *,
    container: bool,
) -> SmtpServer:
    """The SMTP server the environment configures.

    Args:
        environ: The environment (``.env`` loaded into it).
        settings: The names of the variables, and the container's loopback host.
        container: Running in a container, where a loopback host means the Mailpit service.

    Raises:
        MailSetupError: A variable is missing or invalid (the message names it), or a login
            would go unencrypted to a server off this machine.
    """
    names = settings.variables
    server = SmtpServer(
        host=_host(environ, names.host, settings, container),
        port=_port(environ, names.port),
        security=_security(environ, names.security),
        username=environ.get(names.username, "").strip(),
        from_address=_sender(environ, names.from_address),
    )
    _refuse_cleartext_login(server, settings, names.security, container=container)
    return server


def _refuse_cleartext_login(
    server: SmtpServer,
    settings: MailSettings,
    flag: str,
    *,
    container: bool,
) -> None:
    """A login to a server off this machine must be encrypted: never send it in clear text.

    The mail-catcher service counts as local only inside a container, where compose provides it.
    """
    catcher = container and server.host == settings.container_loopback_host
    local = server.host.lower() in _LOOPBACK or catcher
    if server.username and server.security is Security.NONE and not local:
        raise MailSetupError(
            f"Set {flag} to starttls or tls: the SMTP login must not be sent unencrypted.",
        )
