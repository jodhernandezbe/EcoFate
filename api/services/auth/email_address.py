"""Email addresses: validated once at the boundary and stored in one normal form."""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

MAX_LENGTH = 254  # the longest address SMTP allows
INVALID_EMAIL = "Enter a valid email address."


class InvalidEmailError(ValueError):
    """The text is not an email address; ``str(error)`` is safe to show."""


def normalise_email(raw: str) -> str:
    """The address trimmed, with its domain lower-cased (the local part keeps its case).

    No DNS lookup is made: deliverability is proved by the verification mail.

    Raises:
        InvalidEmailError: The text is not a valid address, or is longer than 254 characters.
    """
    text = raw.strip()
    if not text or len(text) > MAX_LENGTH:
        raise InvalidEmailError(INVALID_EMAIL)
    try:
        checked = validate_email(text, check_deliverability=False)
    except EmailNotValidError:
        raise InvalidEmailError(INVALID_EMAIL) from None
    return f"{checked.local_part}@{checked.ascii_domain}"
