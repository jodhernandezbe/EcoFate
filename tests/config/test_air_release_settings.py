"""Tests for the ``[ui.air_release]`` loader."""

from __future__ import annotations

import tomllib

import pytest

from config.air_release import REASONS, AirReleaseRules, parse_air_release
from config.ui import get_ui_settings

TEXT = """
[ui.air_release]
target_unit = "kg"
[ui.air_release.reasons]
none_reported = "a"
unit_not_convertible = "b"
"""


def _parse(text: str) -> AirReleaseRules:
    return parse_air_release(tomllib.loads(text)["ui"], {"Pounds": "pound"})


def test_values() -> None:
    rules = _parse(TEXT)
    assert rules.target_unit == "kg" and rules.reasons["none_reported"] == "a"
    assert rules.aliases["Pounds"] == "pound"


def test_a_missing_reason_is_named() -> None:
    with pytest.raises(ValueError, match="ui.air_release.reasons.unit_not_convertible"):
        _parse(TEXT.replace('unit_not_convertible = "b"', ""))


def test_a_missing_target_unit_is_named() -> None:
    with pytest.raises(ValueError, match="ui.air_release.target_unit"):
        _parse(TEXT.replace('target_unit = "kg"', ""))


def test_shipped_settings_carry_the_tri_aliases() -> None:
    rules = get_ui_settings().air_release
    assert set(rules.reasons) == set(REASONS)
    assert {"Pounds", "Grams"} <= set(rules.aliases)
