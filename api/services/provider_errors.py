"""Plain-language messages for a turn that stopped, safe to show the user.

The runner (``app.turns``) classifies a failure as a ``FailureReason``; this module maps each
reason to one fixed message. The provider's own message is never shown (it can echo request
details). An interrupted turn's message says what happened and what to do before resuming;
when it can no longer be resumed, it says to send a new message instead.
"""

from __future__ import annotations

from types import MappingProxyType

from api.core.exceptions import GENERIC_ERROR
from app.turns import FailureReason, classify

NO_KEY_MESSAGE = "Add your OpenAI API key in Settings (the gear icon) to start."
KEYCHAIN_UNAVAILABLE = "The OS keychain is unavailable."
OUT_OF_CREDITS = (
    "Your OpenAI account has no credits left. Add credits in your OpenAI billing settings "
    "(platform.openai.com), then press Resume to continue where the turn stopped."
)
BAD_KEY = "OpenAI rejected the API key. Replace it in Settings (the gear icon), then press Resume."
RATE_LIMITED = "OpenAI is limiting requests right now. Wait a moment, then press Resume."
PROVIDER_DOWN = (
    "Could not reach OpenAI, or it is having trouble right now. Check your connection, wait a "
    "little, then press Resume."
)
STEP_LIMIT = (
    "The assessment reached the step limit of one run. Press Resume to continue it with a "
    "fresh step budget."
)
WORKER_LOST = (
    "The server stopped while this turn was running. Press Resume to continue from the last "
    "finished step."
)
CANCELLED = "You stopped this turn. Press Resume to continue from the last finished step."
TIME_LIMIT = (
    "This turn ran longer than the time one run may take. Press Resume to continue from the last "
    "finished step."
)
FORBIDDEN = "OpenAI refused the request for this account or model. Check your OpenAI account."
NOT_RESUMABLE = (
    "This turn stopped and cannot be resumed again. Send a new message to continue the assessment."
)

_INTERRUPTION_MESSAGES = MappingProxyType(
    {
        FailureReason.OUT_OF_CREDITS: OUT_OF_CREDITS,
        FailureReason.RATE_LIMITED: RATE_LIMITED,
        FailureReason.BAD_KEY: BAD_KEY,
        FailureReason.PROVIDER_DOWN: PROVIDER_DOWN,
        FailureReason.STEP_LIMIT: STEP_LIMIT,
        FailureReason.WORKER_LOST: WORKER_LOST,
        FailureReason.CANCELLED: CANCELLED,
        FailureReason.TIME_LIMIT: TIME_LIMIT,
    },
)
_PROVIDER_MESSAGES = MappingProxyType(
    {
        reason: _INTERRUPTION_MESSAGES[reason]
        for reason in (
            FailureReason.OUT_OF_CREDITS,
            FailureReason.RATE_LIMITED,
            FailureReason.BAD_KEY,
            FailureReason.PROVIDER_DOWN,
        )
    }
    | {FailureReason.FORBIDDEN: FORBIDDEN},
)
_MESSAGES = MappingProxyType(
    {
        **_INTERRUPTION_MESSAGES,
        FailureReason.FORBIDDEN: FORBIDDEN,
        FailureReason.NO_KEY: NO_KEY_MESSAGE,
        FailureReason.KEYCHAIN_UNAVAILABLE: KEYCHAIN_UNAVAILABLE,
    },
)


def message_for(reason: FailureReason) -> str:
    """The fixed message for a failure reason; the generic one for an unexpected failure."""
    return _MESSAGES.get(reason, GENERIC_ERROR)


def interruption_message(reason: FailureReason, *, resumable: bool) -> str:
    """The fixed message of an interrupted turn: what to do before resuming, or, when it can
    no longer be resumed, to send a new message."""
    return message_for(reason) if resumable else NOT_RESUMABLE


def explain(exc: BaseException) -> str | None:
    """A fixed, user-facing message for a provider failure, or None when it is not one."""
    return _PROVIDER_MESSAGES.get(classify(exc))
