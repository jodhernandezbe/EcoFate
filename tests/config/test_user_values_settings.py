"""Tests for the ``[user_values]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.loader import get_comptox_settings
from config.parsing import DEFAULT_SETTINGS_PATH
from config.user_values import USER_QUANTITIES, load_user_value_settings


def _mutated(tmp_path: Path, old: str, new: str) -> Path:
    text = DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path = tmp_path / "settings.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_shipped_settings_load_every_chemistry_quantity() -> None:
    settings = load_user_value_settings()
    assert set(settings.units) == set(USER_QUANTITIES)
    assert set(settings.ranges) == set(USER_QUANTITIES)


def test_no_stack_quantity_is_listed() -> None:
    settings = load_user_value_settings()
    assert not {"stack_height", "stack_diameter", "exit_velocity", "exit_temperature"} & set(
        settings.units,
    )


def test_first_unit_is_the_target_the_tools_return() -> None:
    settings = load_user_value_settings()
    comptox = get_comptox_settings()
    targets = {p.key: p.target_unit for p in comptox.properties}
    targets.update({t.key: t.target_unit for t in comptox.toxicity_values})
    targets["molecular_weight"] = comptox.molecular_weight.target_unit
    targets["oel_twa"] = "mg/m^3"  # not a CompTox value: the 8-hour occupational limit
    for quantity in USER_QUANTITIES:
        assert settings.units[quantity][0] == targets[quantity], quantity


def test_chemistry_range_is_ordered_and_positive() -> None:
    settings = load_user_value_settings()
    for quantity in USER_QUANTITIES:
        bounds = settings.ranges[quantity]
        assert 0 < bounds.minimum < bounds.maximum


def test_missing_quantity_is_rejected(tmp_path: Path) -> None:
    path = _mutated(tmp_path, 'iur = ["1/(ug/m^3)", "1/(mg/m^3)"]\n', "")
    with pytest.raises(ValueError, match="lacks quantities: iur"):
        load_user_value_settings(path)


def test_stack_quantity_is_rejected_as_unknown(tmp_path: Path) -> None:
    path = _mutated(
        tmp_path,
        'molecular_weight = ["g/mol"]\n',
        'molecular_weight = ["g/mol"]\nstack_height = ["m"]\n',
    )
    with pytest.raises(ValueError, match="unknown quantities: stack_height"):
        load_user_value_settings(path)


def test_duplicate_unit_is_rejected(tmp_path: Path) -> None:
    path = _mutated(tmp_path, '"mmHg", "torr"', '"mmHg", "mmHg"')
    with pytest.raises(ValueError, match="more than once"):
        load_user_value_settings(path)


def test_empty_unit_list_is_rejected(tmp_path: Path) -> None:
    path = _mutated(tmp_path, 'molecular_weight = ["g/mol"]', "molecular_weight = []")
    with pytest.raises(ValueError, match="non-empty list"):
        load_user_value_settings(path)


def test_non_string_unit_is_rejected(tmp_path: Path) -> None:
    path = _mutated(tmp_path, 'molecular_weight = ["g/mol"]', "molecular_weight = [1]")
    with pytest.raises(ValueError, match="unit strings"):
        load_user_value_settings(path)


def test_inverted_range_is_rejected(tmp_path: Path) -> None:
    path = _mutated(tmp_path, "density = [0.1, 25.0]", "density = [25.0, 0.1]")
    with pytest.raises(ValueError, match="minimum must be below maximum"):
        load_user_value_settings(path)


def test_boolean_bound_is_rejected(tmp_path: Path) -> None:
    path = _mutated(tmp_path, "density = [0.1, 25.0]", "density = [true, 25.0]")
    with pytest.raises(ValueError, match="must be a number"):
        load_user_value_settings(path)


def test_missing_section_is_rejected(tmp_path: Path) -> None:
    text = DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8")
    path = tmp_path / "settings.toml"
    path.write_text(text.split("[user_values.units]")[0], encoding="utf-8")
    with pytest.raises(ValueError, match="user_values section is missing"):
        load_user_value_settings(path)
