"""The stored input of an assessment job is untrusted: shape, types and finite numbers."""

from __future__ import annotations

import math

import pytest

from tools.assessment.helpers.job_input import parse_job_input
from tools.schemas import InvalidJobInputError


def test_a_full_input_is_read() -> None:
    request = parse_job_input(
        {
            "arguments": {
                "cas_number": "110-54-3",
                "frs_ids": ["A", "B"],
                "state": "TX",
                "city": "Austin",
                "radius_km": 2,
                "toxicity": {"rfc": 0.7, "iur": None},
            },
            "user_values": {"supplied": {"x": 1.0}, "declined": ["y"]},
        },
    )
    assert request.cas_number == "110-54-3" and request.frs_ids == ["A", "B"]
    assert request.place == ("TX", "Austin") and request.radius_km == 2.0
    assert request.toxicity == {"rfc": 0.7, "iur": None}
    assert request.config == {
        "configurable": {"user_values": {"supplied": {"x": 1.0}, "declined": ["y"]}},
    }


def test_only_the_cas_number_is_required() -> None:
    request = parse_job_input({"arguments": {"cas_number": "110-54-3"}})
    assert request.frs_ids is None and request.toxicity is None and request.config == {}


@pytest.mark.parametrize(
    "stored",
    [
        {},
        {"arguments": []},
        {"arguments": {}},
        {"arguments": {"cas_number": ""}},
        {"arguments": {"cas_number": 110}},
        {"arguments": {"cas_number": "1-1-1", "extra": 1}},
        {"arguments": {"cas_number": "1-1-1", "frs_ids": "A"}},
        {"arguments": {"cas_number": "1-1-1", "frs_ids": [1]}},
        {"arguments": {"cas_number": "1-1-1", "radius_km": True}},
        {"arguments": {"cas_number": "1-1-1", "radius_km": math.nan}},
        {"arguments": {"cas_number": "1-1-1", "radius_km": "3"}},
        {"arguments": {"cas_number": "1-1-1", "toxicity": {"rfc": math.inf}}},
        {"arguments": {"cas_number": "1-1-1", "toxicity": {"other": 1}}},
        {"arguments": {"cas_number": "1-1-1"}, "user_values": [1]},
    ],
)
def test_an_input_that_does_not_fit_is_refused(stored: dict[str, object]) -> None:
    with pytest.raises(InvalidJobInputError):
        parse_job_input(stored)
