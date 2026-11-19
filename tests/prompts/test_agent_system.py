"""Tests for the agent system prompt: it teaches the assessment, it does not list tools."""

from __future__ import annotations

import re

from prompts.registry import load_prompt
from tools.registry import get_all_tools

PROMPT = load_prompt("agent_system")
TAGS = ("role", "context", "instructions", "output_format")


def test_has_the_four_xml_sections_in_order() -> None:
    positions = [PROMPT.index(f"<{tag}>") for tag in TAGS]
    assert positions == sorted(positions)
    assert all(f"</{tag}>" in PROMPT for tag in TAGS)


def test_names_no_tool() -> None:
    """Tools are chosen from their descriptions, so a new tool never needs a prompt edit."""
    named = [t.name for t in get_all_tools() if t.name in PROMPT]
    assert named == []


def test_names_nothing_that_looks_like_a_tool() -> None:
    """Catches a removed tool still being named: no snake_case call-like identifiers."""
    identifiers = re.findall(r"`([a-z]+(?:_[a-z0-9]+)+)`", PROMPT)
    allowed = {"source"}
    assert [i for i in identifiers if i not in allowed] == []


def test_prescribes_no_call_order() -> None:
    assert not re.search(r"(?m)^\s*\d+\.\s", PROMPT)
    assert "first call" not in PROMPT.lower()


def test_requires_visible_quality_signals_and_limits() -> None:
    for text in (
        "source",
        "warnings",
        "Limitations",
        "screening default",
        "never invent, estimate, or convert numbers, names or identifiers yourself",
        "refer to it by its cas number alone, and never add a name of your own",
        "named as the results name it",
        # The CAS rule, in the wording measured clean in 150 of 150 first turns; a paraphrase
        # ("ask for the CAS number and make that your whole reply") fell to 12 of 30.
        "your whole reply is a request for that number",
        "call no tool",
        "write no cas number yourself",
        "asks the user for the number rather than supplying one",
        "a borrowed value is never presented as a measured value",
        "evaluate every one",
        # Every facility is covered: small sources are screened, never dropped by rank.
        "cover every facility of the chemical, not only the largest emitters",
        "a conservative screen shows it cannot reach a level of concern",
        "never end a reply by announcing what you will do next",
    ):
        assert text.lower() in " ".join(PROMPT.split()).lower()  # line wrapping is irrelevant


def test_a_category_match_is_disclosed_and_tried_before_an_analogue() -> None:
    text = " ".join(PROMPT.split()).lower()
    for phrase in (
        "matched through that category",
        "reported releases cover every member together",
        "before looking for an analogue",
        "an analogue is sought only when the chemical is in no category",
        "never taken from the category",
    ):
        assert phrase in text


def test_asks_once_for_missing_values_and_labels_the_users_own() -> None:
    """The missing-value rule: ask once, in one message, and report the user's values as theirs."""
    assert "ask once, in one message" in PROMPT
    assert "user-provided" in PROMPT
    assert "never estimate it in its place" in PROMPT


def _flat() -> str:
    return " ".join(PROMPT.split()).lower()


def test_bands_are_screening_priorities_not_findings() -> None:
    text = _flat()
    assert "high, moderate and low" in text
    assert "never a finding that a limit is exceeded or that an exposure is acceptable" in text


def test_worker_evidence_is_named() -> None:
    text = _flat()
    assert "measured samples from inspections in the same industry come before a model" in text
    assert "the answer says which one each figure rests on" in text


def test_fugitive_release_is_context_not_worker_exposure() -> None:
    assert "not a measure of what a worker breathes" in _flat()


def test_workers_and_neighbours_side_by_side_and_not_compliance() -> None:
    text = _flat()
    assert "side by side" in text
    assert "never as a compliance finding" in text
    assert "reported as not computed, with the reason" in text
