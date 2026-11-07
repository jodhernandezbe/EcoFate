"""Plain-language messages for a failed turn, safe to show the user.

The runner (``app.turns``) classifies a failure as a ``FailureReason``; this module maps each
reason to one fixed message. The provider's own message is never shown (it can echo request
details).
"""

from __future__ import annotations

from types import MappingProxyType

from api.core.exceptions import GENERIC_ERROR
from app.turns import FailureReason, classify

NO_KEY_MESSAGE = "Add your OpenAI API key in Settings (the gear icon) to start."
KEYCHAIN_UNAVAILABLE = "The OS keychain is unavailable."
OUT_OF_CREDITS = (
    "Your OpenAI account has no credits left. Add credits in your OpenAI billing settings "
    "(platform.openai.com), then try again."
)
BAD_KEY = "OpenAI rejected the API key. Check or replace it in Settings (the gear icon)."
RATE_LIMITED = "OpenAI is limiting requests right now. Wait a moment and try again."
UNREACHABLE = "Could not reach OpenAI. Check your connection and try again."
PROVIDER_DOWN = "OpenAI is having trouble right now. Try again in a little while."
FORBIDDEN = "OpenAI refused the request for this account or model. Check your OpenAI account."

_PROVIDER_MESSAGES = MappingProxyType(
    {
        FailureReason.OUT_OF_CREDITS: OUT_OF_CREDITS,
        FailureReason.RATE_LIMITED: RATE_LIMITED,
        FailureReason.BAD_KEY: BAD_KEY,
        FailureReason.FORBIDDEN: FORBIDDEN,
        FailureReason.PROVIDER_DOWN: PROVIDER_DOWN,
        FailureReason.UNREACHABLE: UNREACHABLE,
    },
)
_MESSAGES = MappingProxyType(
    {
        **_PROVIDER_MESSAGES,
        FailureReason.NO_KEY: NO_KEY_MESSAGE,
        FailureReason.KEYCHAIN_UNAVAILABLE: KEYCHAIN_UNAVAILABLE,
    },
)


def message_for(reason: FailureReason) -> str:
    """The fixed message for a failure reason; the generic one for an unexpected failure."""
    return _MESSAGES.get(reason, GENERIC_ERROR)


def explain(exc: BaseException) -> str | None:
    """A fixed, user-facing message for a provider failure, or None when it is not one."""
    return _PROVIDER_MESSAGES.get(classify(exc))
