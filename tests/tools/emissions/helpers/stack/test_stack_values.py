"""Tests for stack row validation and conversion."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from config.stack import StackSettings, load_stack_settings
from tools.emissions.helpers.stack.stack_values import check_units_convertible, stack_values

COLUMNS = MappingProxyType(
    {"stack_height": "h", "stack_diameter": "d", "exit_velocity": "v", "exit_temperature": "t"},
)
SI = MappingProxyType(
    {"stack_height": "m", "stack_diameter": "m", "exit_velocity": "m/s", "exit_temperature": "K"},
)
IMPERIAL = MappingProxyType(
    {
        "stack_height": "ft",
        "stack_diameter": "ft",
        "exit_velocity": "ft/s",
        "exit_temperature": "degF",
    },
)
ROW = {"h": "10", "d": "1", "v": "5", "t": "400"}


@pytest.fixture
def settings() -> StackSettings:
    return load_stack_settings()


def test_si_row(settings: StackSettings) -> None:
    values, problems = stack_values(ROW, COLUMNS, SI, settings, None)
    assert problems == []
    assert dict(values or {}) == {
        "stack_height": 10.0,
        "stack_diameter": 1.0,
        "exit_velocity": 5.0,
        "exit_temperature": 400.0,
    }


def test_imperial_row_converted(settings: StackSettings) -> None:
    row = {"h": "10", "d": "1", "v": "10", "t": "32"}
    values, _ = stack_values(row, COLUMNS, IMPERIAL, settings, None)
    assert values is not None
    assert values["stack_height"] == pytest.approx(3.048)
    assert values["stack_diameter"] == pytest.approx(0.3048)
    assert values["exit_velocity"] == pytest.approx(3.048)
    assert values["exit_temperature"] == pytest.approx(273.15)


@pytest.mark.parametrize(
    ("column", "cell", "message"),
    [
        ("h", "N/A", "stack_height is missing or not a finite number"),
        ("h", "", "stack_height is missing"),
        ("h", "inf", "stack_height is missing or not a finite number"),
        ("h", "nan", "stack_height is missing or not a finite number"),
        ("h", "True", "stack_height is missing or not a finite number"),
        ("d", "0", "stack_diameter 0 m is outside the plausible range"),
        ("v", "-2", "exit_velocity -2 m/s is outside the plausible range"),
        ("t", "100", "exit_temperature 100 K is outside the plausible range"),
        ("h", "1000", "stack_height 1000 m is outside the plausible range"),
    ],
)
def test_bad_cell_rejects_whole_row(
    settings: StackSettings,
    column: str,
    cell: str,
    message: str,
) -> None:
    values, problems = stack_values({**ROW, column: cell}, COLUMNS, SI, settings, None)
    assert values is None
    assert len(problems) == 1
    assert problems[0].startswith(message)


def test_missing_column_rejects_row(settings: StackSettings) -> None:
    row = {k: v for k, v in ROW.items() if k != "t"}
    values, problems = stack_values(row, COLUMNS, SI, settings, None)
    assert values is None
    assert "exit_temperature is missing" in problems[0]


def test_every_problem_reported(settings: StackSettings) -> None:
    _, problems = stack_values(
        {"h": "x", "d": "x", "v": "5", "t": "400"},
        COLUMNS,
        SI,
        settings,
        None,
    )
    assert len(problems) == 2


def test_units_convertible(settings: StackSettings) -> None:
    check_units_convertible(IMPERIAL, settings, None)


def test_unconvertible_unit_raises(settings: StackSettings) -> None:
    units = MappingProxyType({**SI, "exit_velocity": "kg"})
    with pytest.raises(ValueError, match="exit_velocity"):
        check_units_convertible(units, settings, None)
