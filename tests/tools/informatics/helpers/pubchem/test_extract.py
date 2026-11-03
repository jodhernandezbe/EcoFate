"""Tests for the field-driven extraction from a PUG View record (synthetic values)."""

from __future__ import annotations

import pytest

from config.pubchem import FieldSpec, get_pubchem_settings
from tests.tools.informatics.helpers.pubchem.records import info, record
from tools.informatics.helpers.pubchem.extract import FieldValue, extract_field
from tools.informatics.helpers.pubchem.result import Lookup

SETTINGS = get_pubchem_settings()
FIELDS = {spec.key: spec for spec in SETTINGS.fields}
ALIASES = {"mm Hg": "mmHg", "g/cu cm": "g/cm^3", "kg/cu m": "kg/m^3"}
RATIO = SETTINGS.agreement_ratio


def _pressure(*texts: str) -> object:
    return record(pressure=[info(t) for t in texts])


def _extract(body: object, key: str) -> Lookup[FieldValue]:
    return extract_field(body, FIELDS[key], RATIO, ALIASES)


def test_molecular_weight_from_a_structured_entry() -> None:
    found = _extract(record(weight=[info("100.5", "g/mol")]), "molecular_weight")
    assert found.value is not None
    assert (found.value.value, found.value.unit, found.value.count) == (100.5, "g/mol", 1)


def test_vapor_pressure_in_the_window_is_converted() -> None:
    found = _extract(_pressure("7 mm Hg at 25 °C"), "vapor_pressure")
    assert found.value is not None and found.value.value == pytest.approx(7.0)
    assert found.value.unit == "mmHg"


def test_vapor_pressure_in_another_unit_is_converted() -> None:
    found = _extract(_pressure("Vapor pressure, kPa at 20 °C: 1"), "vapor_pressure")
    assert found.value is not None and found.value.value == pytest.approx(7.50062, rel=1e-4)


def test_density_in_kg_per_m3_is_converted() -> None:
    found = _extract(record(density=[info("Density, kg/cu m: 500")]), "density")
    assert found.value is not None and found.value.value == pytest.approx(0.5)


def test_agreeing_statements_give_their_median() -> None:
    found = _extract(
        _pressure("6 mmHg at 20 °C", "8 mmHg at 25 °C", "7 mmHg at 22 °C"),
        "vapor_pressure",
    )
    assert found.value is not None and found.value.value == 7.0 and found.value.count == 3


def test_one_clear_statement_among_unclear_ones() -> None:
    body = _pressure("1-2 mmHg", "7 mmHg at 25 °C", "no number here")
    found = _extract(body, "vapor_pressure")
    assert found.value is not None and found.value.value == 7.0 and found.value.count == 1


def test_conflicting_statements_give_no_value() -> None:
    found = _extract(_pressure("1 mmHg at 20 °C", "9 mmHg at 25 °C"), "vapor_pressure")
    assert found.value is None and found.reason is not None and "disagree" in found.reason


def test_temperature_outside_the_window_is_refused() -> None:
    found = _extract(_pressure("7 mmHg at 9.8 °C", "7 mmHg at 35 °C"), "vapor_pressure")
    assert found.value is None and found.reason is not None and "outside" in found.reason


def test_fahrenheit_temperature_is_checked_in_celsius() -> None:
    assert _extract(_pressure("7 mmHg at 77 °F"), "vapor_pressure").value is not None
    assert _extract(_pressure("7 mmHg at 32 °F"), "vapor_pressure").value is None


def test_vapor_pressure_without_a_temperature_is_refused() -> None:
    found = _extract(_pressure("7 mmHg", "2 atm"), "vapor_pressure")
    assert found.value is None and found.reason is not None and "no temperature" in found.reason


def test_density_without_a_temperature_is_allowed_when_it_has_a_unit() -> None:
    found = _extract(record(density=[info("Density, g/cu cm: 0.5")]), "density")
    assert found.value is not None and found.value.value == 0.5


def test_unitless_density_is_refused() -> None:
    found = _extract(
        record(density=[info("0.5"), info("Relative density (water = 1): 0.5")]),
        "density",
    )
    assert found.value is None and found.reason is not None


def test_density_outside_its_window_is_refused() -> None:
    found = _extract(record(density=[info("0.5 g/cu cm at 60 °C")]), "density")
    assert found.value is None


def test_a_unit_of_another_dimension_is_refused() -> None:
    found = _extract(_pressure("7 g/cu cm at 25 °C"), "vapor_pressure")
    assert found.value is None and found.reason is not None and "does not convert" in found.reason


def test_zero_and_negative_values_are_refused() -> None:
    assert _extract(_pressure("0 mmHg at 25 °C"), "vapor_pressure").value is None
    assert _extract(_pressure("-3 mmHg at 25 °C"), "vapor_pressure").value is None


def test_missing_section_gives_a_reason() -> None:
    found = _extract(record(cas=["106-97-8"]), "density")
    assert found.value is None and found.reason is not None and "density" in found.reason


@pytest.mark.parametrize("bad", [None, [], "x", {}, {"Record": 5}, {"Record": {"Section": [None]}}])
def test_unrelated_records_give_no_value_and_do_not_raise(bad: object) -> None:
    for key in FIELDS:
        assert _extract(bad, key).value is None


def test_a_field_added_to_the_configuration_is_extracted_with_no_code_change() -> None:
    spec = FieldSpec(
        key="vapor_pressure",
        heading=("Chemical and Physical Properties", "Experimental Properties", "Density"),
        target_unit="g/cm^3",
        min_celsius=None,
        max_celsius=None,
        allow_missing_temperature=True,
    )
    body = record(density=[info("0.25 g/cu cm at 5 °C")])
    found = extract_field(body, spec, RATIO, ALIASES)
    assert found.value is not None and found.value.value == 0.25
