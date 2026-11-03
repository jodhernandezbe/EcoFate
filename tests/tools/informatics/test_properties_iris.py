"""The IRIS endpoint's notes reach the warnings of fetch_chemical_properties (no network)."""

from __future__ import annotations

from config.loader import get_comptox_settings, get_unit_settings
from tests.tools.informatics.pubchem_fakes import StubComptox
from tools.informatics.properties import lookup_chemical_properties
from tools.schemas import ChemicalProperties, ToxicityValue

CAS = "106-97-8"
RFC: ToxicityValue = {
    "value": 0.2,
    "unit": "mg/m3",
    "source": "EPA IRIS: IRIS (CompTox IRIS endpoint)",
    "route": "inhalation",
    "endpoint": "Respiratory",
    "assessment": "non-cancer",
}
NOTE = "rfc: the IRIS endpoint gives 0.2 mg/m3 but the ToxVal copy of IRIS gives 0.35 mg/m3"


def _run(notes: list[str]) -> ChemicalProperties:
    comptox = StubComptox(weight=50.0, toxicity={"rfc": RFC}, name="stub", notes=notes)
    return lookup_chemical_properties(
        CAS,
        comptox,
        get_comptox_settings(),
        get_unit_settings().aliases,
        None,
    )


def test_notes_are_warnings_and_the_value_is_reported() -> None:
    result = _run([NOTE])
    assert NOTE in result["warnings"]
    assert result["rfc"] == 0.2
    assert result["toxicity_details"]["rfc"]["endpoint"] == "Respiratory"


def test_no_notes_add_no_warning() -> None:
    assert NOTE not in _run([])["warnings"]
