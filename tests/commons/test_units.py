"""Tests for commons.units."""

from __future__ import annotations

import math

import pytest

from commons.units import UnitConversionError, convert


def test_compatible_units() -> None:
    assert convert(2500.0, "ug/m^3", "mg/m^3") == pytest.approx(2.5)


def test_same_unit_unchanged() -> None:
    assert convert(3.5, "mmHg", "mmHg") == 3.5


def test_reciprocal_units() -> None:
    assert convert(2.0, "(ug/m^3)^-1", "(mg/m^3)^-1") == pytest.approx(2000.0)
    assert convert(2.0, "1/(ug/m^3)", "1/(mg/m^3)") == pytest.approx(2000.0)


def test_pressure_factor() -> None:
    assert convert(1.0, "mmHg", "Pa") == pytest.approx(133.322387415, rel=1e-6)


def test_dose_units() -> None:
    assert convert(1.0, "g/(kg*day)", "mg/(kg*day)") == pytest.approx(1000.0)


def test_dimension_mismatch_names_both_units() -> None:
    with pytest.raises(UnitConversionError, match=r"g/cm\^3.*mmHg"):
        convert(1.0, "g/cm^3", "mmHg")


@pytest.mark.parametrize("unit", ["not_a_unit", "", "m//s", "((", "ug/m3"])
def test_unknown_or_malformed_unit(unit: str) -> None:
    with pytest.raises(UnitConversionError, match="cannot convert"):
        convert(1.0, unit, "mg/m^3")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_value(value: float) -> None:
    with pytest.raises(UnitConversionError):
        convert(value, "mg/m^3", "mg/m^3")


def test_alias_on_source_and_target() -> None:
    aliases = {"mg/m3": "mg/m^3", "ug/m3": "ug/m^3"}
    assert convert(1.0, "mg/m3", "ug/m3", aliases) == pytest.approx(1000.0)
    assert convert(1.0, " mg/m3 ", "ug/m^3", aliases) == pytest.approx(1000.0)


def test_alias_added_later() -> None:
    with pytest.raises(UnitConversionError):
        convert(1.0, "mg/m3", "ug/m^3", {})
    assert convert(1.0, "mg/m3", "ug/m^3", {"mg/m3": "mg/m^3"}) == pytest.approx(1000.0)


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (32.0, "degF", "K", 273.15),
        (72.05, "degF", "K", 295.4),
        (0.0, "degC", "K", 273.15),
        (9.84, "ft", "m", 2.9992),
        (13.12, "ft/s", "m/s", 3.9990),
    ],
)
def test_absolute_temperature_and_length(
    value: float,
    source: str,
    target: str,
    expected: float,
) -> None:
    assert convert(value, source, target) == pytest.approx(expected, abs=1e-3)
