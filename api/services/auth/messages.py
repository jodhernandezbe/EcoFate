"""The account emails: fixed text, with the one link each carries.

A link opens the app with the token in the URL fragment (``#verify=…`` / ``#reset=…``), which
the browser never sends to a server, so it appears in no access log and no ``Referer``.
"""

from __future__ import annotations

from api.services.auth.mailer import Mail

VERIFY_SUBJECT = "Verify your EcoFate email"
RESET_SUBJECT = "Reset your EcoFate password"
EXISTING_SUBJECT = "You already have an EcoFate account"
_IGNORE = "If you did not ask for this, you can ignore this email; nothing was changed."


def fragment_link(base_url: str, kind: str, token: str) -> str:
    """``{base_url}/#{kind}={token}``."""
    return f"{base_url}/#{kind}={token}"


def verification_mail(to: str, base_url: str, token: str) -> Mail:
    """The email that carries the address-verification link."""
    link = fragment_link(base_url, "verify", token)
    body = f"Open this link to verify your email address:\n\n{link}\n\n{_IGNORE}\n"
    return Mail(to, VERIFY_SUBJECT, body)


def reset_mail(to: str, base_url: str, token: str) -> Mail:
    """The email that carries the password-reset link."""
    link = fragment_link(base_url, "reset", token)
    body = f"Open this link to choose a new password:\n\n{link}\n\n{_IGNORE}\n"
    return Mail(to, RESET_SUBJECT, body)


def existing_account_mail(to: str, base_url: str) -> Mail:
    """The email an address gets when someone signs up with it again (no token, no change)."""
    body = (
        "Someone tried to create an EcoFate account with this email address, which already "
        f"has one. Sign in at {base_url}/ or, if you forgot your password, use "
        f"“Forgot password” there.\n\n{_IGNORE}\n"
    )
    return Mail(to, EXISTING_SUBJECT, body)
