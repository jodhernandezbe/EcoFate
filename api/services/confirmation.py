"""Confirmation replies: checked against the open request, recorded in the thread, and shown.

A reply is checked before the turn starts, so a rejected reply changes nothing. Values are
checked with the same rules the tools use (units, finite numbers, plausible range); a browser's
check is convenience only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.schemas.chat import ChatRequest, ConfirmationRequested, EntryAnswer, MissingValue
from api.services.threads import ThreadStore
from config.loader import get_unit_settings
from config.user_values import get_user_value_settings
from tools.schemas import ConfirmationRequest, MissingEntry
from tools.user_values import check_entered_value

CLOSED = "That request is no longer open; the values it asked for are not needed any more."
NOT_LISTED = "The answer names a value that the open request does not ask for: {key}."
INCOMPLETE = "Answer every value in the request: {keys} still has no answer."
ENTER = "{key}: enter a number and choose its unit."


class ConfirmationError(Exception):
    """A reply that cannot be applied; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class TurnPlan:
    """What the turn says to the agent: the user's message and a note on the answers so far.

    Attributes:
        message: The text of the user's turn (a summary when the turn carries answers).
        note: Facts about the thread's answers, for the model's instructions; may be empty.
    """

    message: str
    note: str


def _index(pending: ConfirmationRequest) -> dict[str, MissingEntry]:
    return {entry["entry_id"]: entry for entry in pending["entries"]}


def _check_listed(answers: Sequence[EntryAnswer], entries: Mapping[str, MissingEntry]) -> None:
    for answer in answers:
        if answer.entry_id not in entries:
            raise ConfirmationError(422, NOT_LISTED.format(key=answer.entry_id))
    given = [answer.entry_id for answer in answers]
    unanswered = [key for key in entries if key not in given]
    if unanswered or len(set(given)) != len(given):
        raise ConfirmationError(422, INCOMPLETE.format(keys=", ".join(unanswered) or "an entry"))


def _supplied_value(answer: EntryAnswer, entry: MissingEntry) -> float:
    """The answer's value in the target unit; raises when it cannot be used."""
    if answer.number is None or answer.unit is None:
        raise ConfirmationError(422, ENTER.format(key=answer.entry_id))
    settings = get_user_value_settings()
    result = check_entered_value(
        entry["quantity"],
        answer.number,
        answer.unit,
        settings,
        get_unit_settings().aliases,
    )
    if result.value is None:
        raise ConfirmationError(422, f"{answer.entry_id}: {result.reason}")
    return result.value


def _describe(answer: EntryAnswer, entry: MissingEntry) -> str:
    if answer.decision == "decline":
        return f"proceed without {entry['quantity']} for {entry['subject']}"
    return f"{entry['quantity']} for {entry['subject']} = {answer.number} {answer.unit}"


async def _record(
    threads: ThreadStore,
    thread_id: str,
    answers: Sequence[EntryAnswer],
    index: Mapping[str, MissingEntry],
) -> str:
    """Store the answers in the thread and return the summary of what was answered."""
    supplied: dict[str, float] = {}
    declined: list[str] = []
    parts: list[str] = []
    for answer in answers:
        entry = index[answer.entry_id]
        parts.append(_describe(answer, entry))
        if answer.decision == "decline":
            declined.append(answer.entry_id)
        else:
            supplied[answer.entry_id] = _supplied_value(answer, entry)
    await threads.record_answers(thread_id, supplied, declined)
    return "; ".join(parts)


def _answers_note(supplied: Mapping[str, float], declined: Sequence[str]) -> str:
    """Facts the model must respect: values in hand and entries the user will not supply."""
    lines: list[str] = []
    if supplied:
        values = ", ".join(f"{key} = {value:g} (target unit)" for key, value in supplied.items())
        lines.append(f"The user supplied these values; use them, and never ask again: {values}.")
    if declined:
        lines.append(
            "The user chose to proceed without these values; report them as absent and do not "
            f"ask again: {', '.join(declined)}.",
        )
    return " ".join(lines)


async def _all_declined(threads: ThreadStore, thread_id: str, pending: ConfirmationRequest) -> str:
    """A new message while a request is open: its entries count as proceed without.

    Returns the note for the model.
    """
    keys = [entry["entry_id"] for entry in pending["entries"]]
    await threads.record_answers(thread_id, {}, keys)
    await threads.set_pending(thread_id, None)
    supplied, declined = await threads.answers(thread_id)
    return f"The user did not answer the open request. {_answers_note(supplied, sorted(declined))}"


async def plan_turn(request: ChatRequest, threads: ThreadStore) -> TurnPlan:
    """Check the reply against the open request, record it, and say what the turn starts with.

    Raises:
        ConfirmationError: 409 when no request is open or the reply names another one; 422 when
            an answer is incomplete, names a value not asked for, or is out of range. Nothing is
            recorded when it raises.
    """
    pending = await threads.pending(request.thread_id)
    if request.answers is None:
        return await _plan_free_message(request, threads, pending)
    if pending is None or pending["request_id"] != request.answers.request_id:
        raise ConfirmationError(409, CLOSED)
    index = _index(pending)
    _check_listed(request.answers.entries, index)
    summary = await _record(threads, request.thread_id, request.answers.entries, index)
    await threads.set_pending(request.thread_id, None)
    supplied, declined = await threads.answers(request.thread_id)
    return TurnPlan(
        message=f"Answers to the open request: {summary}.",
        note=_answers_note(supplied, sorted(declined)),
    )


async def _plan_free_message(
    request: ChatRequest,
    threads: ThreadStore,
    pending: ConfirmationRequest | None,
) -> TurnPlan:
    if pending is None:
        supplied, declined = await threads.answers(request.thread_id)
        note = _answers_note(supplied, sorted(declined))
        return TurnPlan(message=request.message, note=note)
    note = await _all_declined(threads, request.thread_id, pending)
    return TurnPlan(message=request.message, note=note)


def request_event(seq: int, request: ConfirmationRequest) -> ConfirmationRequested:
    """The stream event that shows an open request to the user."""
    return ConfirmationRequested(
        seq=seq,
        request_id=request["request_id"],
        entries=[
            MissingValue(
                entry_id=entry["entry_id"],
                quantity=entry["quantity"],
                subject=entry["subject"],
                accepted_units=entry["accepted_units"],
                minimum=entry["minimum"],
                maximum=entry["maximum"],
                purpose=entry["purpose"],
            )
            for entry in request["entries"]
        ],
    )
