"""Tests for the ``[limits]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.limits import get_limit_settings, load_limit_settings

LIMITS_FILE = """
[limits]
enabled = true
daily_turns_per_user = 3
admin_exempt = true
retention_days = 10
exhausted_message = "Used up for today."
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_values(tmp_path: Path) -> None:
    settings = load_limit_settings(_write(tmp_path, LIMITS_FILE))
    assert settings.enabled is True
    assert settings.daily_turns_per_user == 3
    assert settings.admin_exempt is True
    assert settings.retention_days == 10
    assert settings.exhausted_message == "Used up for today."


def test_shipped_settings() -> None:
    settings = get_limit_settings()
    assert settings.daily_turns_per_user >= 1
    assert settings.exhausted_message


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("daily_turns_per_user = 3", "daily_turns_per_user = 0", "limits.daily_turns_per_user"),
        ("daily_turns_per_user = 3", "daily_turns_per_user = -2", "limits.daily_turns_per_user"),
        ("daily_turns_per_user = 3", "daily_turns_per_user = true", "limits.daily_turns_per_user"),
        ("daily_turns_per_user = 3", "daily_turns_per_user = 2.5", "limits.daily_turns_per_user"),
        ("daily_turns_per_user = 3", 'daily_turns_per_user = "3"', "limits.daily_turns_per_user"),
        ("retention_days = 10", "retention_days = 0", "limits.retention_days"),
        ("enabled = true", "enabled = 1", "limits.enabled"),
        ("admin_exempt = true", 'admin_exempt = "yes"', "limits.admin_exempt"),
        (
            'exhausted_message = "Used up for today."',
            'exhausted_message = "  "',
            "exhausted_message",
        ),
        ('exhausted_message = "Used up for today."', "exhausted_message = 4", "exhausted_message"),
    ],
)
def test_invalid_value_names_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_limit_settings(_write(tmp_path, LIMITS_FILE.replace(old, new)))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="limits"):
        load_limit_settings(_write(tmp_path, LIMITS_FILE.replace("[limits]", "[other]")))
