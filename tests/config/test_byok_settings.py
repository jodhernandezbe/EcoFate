"""Tests for the ``[byok]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.byok import get_byok_settings, load_byok_settings

BYOK_FILE = """
[byok]
kek_env_var = "TEST_KEK"  # pragma: allowlist secret
previous_kek_env_var = "TEST_KEK_PREVIOUS"  # pragma: allowlist secret
rotation_batch_size = 50
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_values(tmp_path: Path) -> None:
    settings = load_byok_settings(_write(tmp_path, BYOK_FILE))
    assert settings.kek_env_var == "TEST_KEK"  # pragma: allowlist secret
    assert settings.previous_kek_env_var == "TEST_KEK_PREVIOUS"  # pragma: allowlist secret
    assert settings.rotation_batch_size == 50


def test_shipped_settings() -> None:
    settings = get_byok_settings()
    assert settings.kek_env_var == "ECOFATE_KEY_ENCRYPTION_KEY"  # pragma: allowlist secret
    assert settings.rotation_batch_size >= 1


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ('kek_env_var = "TEST_KEK"', 'kek_env_var = " "', "kek_env_var"),
        ('kek_env_var = "TEST_KEK"', "kek_env_var = 3", "byok.kek_env_var"),
        ('previous_kek_env_var = "TEST_KEK_PREVIOUS"', 'previous_kek_env_var = ""', "previous"),
        (
            'previous_kek_env_var = "TEST_KEK_PREVIOUS"',
            'previous_kek_env_var = "TEST_KEK"',
            "differ",
        ),
        ("rotation_batch_size = 50", "rotation_batch_size = 0", "byok.rotation_batch_size"),
        ("rotation_batch_size = 50", "rotation_batch_size = -4", "byok.rotation_batch_size"),
        ("rotation_batch_size = 50", "rotation_batch_size = true", "byok.rotation_batch_size"),
    ],
)
def test_invalid_value_names_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_byok_settings(_write(tmp_path, BYOK_FILE.replace(old, new)))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="byok"):
        load_byok_settings(_write(tmp_path, BYOK_FILE.replace("[byok]", "[other]")))
