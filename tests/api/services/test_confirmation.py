"""Tests for checking, recording and showing confirmation replies."""

from __future__ import annotations

import pytest

from api.schemas.chat import ChatRequest
from api.services.confirmation import ConfirmationError, plan_turn, request_event
from api.services.threads import ThreadStore
from tools.schemas import ConfirmationRequest, MissingEntry

THREAD = "t1"
IUR = "iur:71-43-2"
RFC = "rfc:71-43-2"


def _entry(entry_id: str, quantity: str) -> MissingEntry:
    return MissingEntry(
        entry_id=entry_id,
        quantity=quantity,
        subject="71-43-2",
        accepted_units=["1/(ug/m^3)", "1/(mg/m^3)"] if quantity == "iur" else ["mg/m^3", "ug/m^3"],
        minimum=1e-9 if quantity == "iur" else 1e-8,
        maximum=1000.0,
        purpose="the cancer risk",
    )


def _open(threads: ThreadStore, *keys: tuple[str, str]) -> ConfirmationRequest:
    request = ConfirmationRequest(
        request_id="req1",
        entries=[_entry(key, quantity) for key, quantity in keys],
    )
    threads.set_pending(THREAD, request)
    return request


def _reply(entries: list[dict[str, object]], request_id: str = "req1") -> ChatRequest:
    return ChatRequest.model_validate(
        {"thread_id": THREAD, "answers": {"request_id": request_id, "entries": entries}},
    )


def _supply(entry_id: str, number: float, unit: str) -> dict[str, object]:
    return {"entry_id": entry_id, "decision": "supply", "number": number, "unit": unit}


def _decline(entry_id: str) -> dict[str, object]:
    return {"entry_id": entry_id, "decision": "decline"}


def test_valid_answer_is_recorded_in_target_unit_and_closes_the_request() -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"))
    plan = plan_turn(_reply([_supply(IUR, 0.002, "1/(mg/m^3)")]), threads)
    supplied, declined = threads.answers(THREAD)
    assert supplied[IUR] == pytest.approx(2e-6)
    assert declined == frozenset()
    assert threads.pending(THREAD) is None
    assert "iur for 71-43-2 = 0.002 1/(mg/m^3)" in plan.message
    assert "supplied" in plan.note


def test_decline_is_recorded_and_the_note_says_not_to_ask_again() -> None:
    threads = ThreadStore()
    _open(threads, (RFC, "rfc"))
    plan = plan_turn(_reply([_decline(RFC)]), threads)
    assert threads.answers(THREAD)[1] == frozenset({RFC})
    assert "proceed without these values" in plan.note
    assert "do not ask again" in plan.note


def test_reply_to_a_closed_or_other_request_is_409_and_changes_nothing() -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"))
    with pytest.raises(ConfirmationError) as closed:
        plan_turn(_reply([_supply(IUR, 2e-6, "1/(ug/m^3)")], request_id="other"), threads)
    assert closed.value.status == 409
    assert threads.pending(THREAD) is not None
    assert threads.answers(THREAD) == ({}, frozenset())


def test_reply_with_no_open_request_is_409() -> None:
    threads = ThreadStore()
    with pytest.raises(ConfirmationError) as closed:
        plan_turn(_reply([_decline(IUR)]), threads)
    assert closed.value.status == 409


def test_answer_for_an_entry_not_asked_is_422_and_changes_nothing() -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"))
    with pytest.raises(ConfirmationError) as bad:
        plan_turn(_reply([_supply("rfc:other", 1.0, "mg/m^3")]), threads)
    assert bad.value.status == 422
    assert threads.pending(THREAD) is not None
    assert threads.answers(THREAD) == ({}, frozenset())


def test_unanswered_entry_is_422() -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"), (RFC, "rfc"))
    with pytest.raises(ConfirmationError, match=RFC) as incomplete:
        plan_turn(_reply([_decline(IUR)]), threads)
    assert incomplete.value.status == 422


def test_repeated_entry_is_422() -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"))
    with pytest.raises(ConfirmationError) as repeated:
        plan_turn(_reply([_decline(IUR), _decline(IUR)]), threads)
    assert repeated.value.status == 422


@pytest.mark.parametrize(
    ("number", "unit"),
    [
        (4500.0, "m"),  # not an accepted unit for an IUR
        (0.0, "1/(ug/m^3)"),  # zero is below the plausible range
        (-2e-6, "1/(ug/m^3)"),  # negative
        (None, "1/(ug/m^3)"),  # no number
        (2e-6, None),  # no unit
    ],
)
def test_out_of_range_or_incomplete_value_is_422_and_changes_nothing(
    number: float | None,
    unit: str | None,
) -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"))
    entry: dict[str, object] = {
        "entry_id": IUR,
        "decision": "supply",
        "number": number,
        "unit": unit,
    }
    with pytest.raises(ConfirmationError) as bad:
        plan_turn(_reply([entry]), threads)
    assert bad.value.status == 422
    assert threads.pending(THREAD) is not None
    assert threads.answers(THREAD) == ({}, frozenset())


def test_free_message_while_open_counts_every_entry_as_declined() -> None:
    threads = ThreadStore()
    _open(threads, (IUR, "iur"), (RFC, "rfc"))
    message = ChatRequest.model_validate({"thread_id": THREAD, "message": "what about benzene?"})
    plan = plan_turn(message, threads)
    assert threads.pending(THREAD) is None
    assert threads.answers(THREAD)[1] == frozenset({IUR, RFC})
    assert plan.message == "what about benzene?"
    assert "did not answer" in plan.note


def test_free_message_with_nothing_open_has_no_note_about_answers() -> None:
    threads = ThreadStore()
    message = ChatRequest.model_validate({"thread_id": THREAD, "message": "hello"})
    plan = plan_turn(message, threads)
    assert plan.note == ""
    assert plan.message == "hello"


def test_a_recorded_value_is_never_replaced_by_a_later_answer() -> None:
    threads = ThreadStore()
    threads.record_answers(THREAD, {IUR: 1e-6}, [])
    threads.record_answers(THREAD, {IUR: 5e-6}, [])
    assert threads.answers(THREAD)[0] == {IUR: 1e-6}


def test_request_event_lists_each_entry_for_the_user() -> None:
    event = request_event(7, ConfirmationRequest(request_id="req1", entries=[_entry(IUR, "iur")]))
    assert event.seq == 7
    assert event.type == "confirmation_request"
    assert event.entries[0].accepted_units[0] == "1/(ug/m^3)"
    assert event.entries[0].entry_id == IUR
