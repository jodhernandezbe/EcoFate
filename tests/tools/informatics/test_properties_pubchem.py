"""Tests for the PubChem fallback inside fetch_chemical_properties (no network)."""

from __future__ import annotations

import pytest

from config.loader import get_comptox_settings, get_unit_settings
from config.pubchem import get_pubchem_settings
from tests.tools.informatics.helpers.pubchem.fakes import FakeJson
from tests.tools.informatics.helpers.pubchem.records import info, record
from tests.tools.informatics.pubchem_fakes import FakePubchem, StubComptox, offer
from tools.http import HttpRequestError
from tools.informatics.helpers.comptox import ComptoxLookup
from tools.informatics.helpers.pubchem import PubchemCandidates, PubchemFallback, PubchemLookup
from tools.informatics.properties import lookup_chemical_properties
from tools.schemas import ChemicalProperties, PropertyValue

CAS = "106-97-8"
OTHER_CAS = "71-43-2"
CID = 7843
SETTINGS = get_pubchem_settings()
ALIASES = get_unit_settings().aliases
PRESSURE: PropertyValue = {"value": 11.0, "unit": "mmHg", "source": "experimental"}
DENSITY: PropertyValue = {"value": 0.25, "unit": "g/cm^3", "source": "predicted"}


def _run(
    comptox: ComptoxLookup,
    pubchem: PubchemFallback | None,
    cas: str = CAS,
) -> ChemicalProperties:
    return lookup_chemical_properties(cas, comptox, get_comptox_settings(), ALIASES, pubchem)


def _real(body: object, cas_in_search: str = CAS) -> PubchemLookup:
    answers = {
        SETTINGS.name_url(cas_in_search): {"IdentifierList": {"CID": [CID]}},
        SETTINGS.record_url(CID): body,
    }
    return PubchemLookup(FakeJson(answers), SETTINGS, ALIASES)


def _complete_comptox() -> StubComptox:
    return StubComptox(
        weight=50.0,
        properties={"vapor_pressure": PRESSURE, "density": DENSITY},
        name="stub",
    )


def test_pubchem_is_not_asked_when_nothing_is_missing() -> None:
    fake = FakePubchem(offer(density=(9.0, "g/cm^3")))
    result = _run(_complete_comptox(), fake)
    assert fake.calls == []
    assert result["density"] == 0.25 and "PubChem" not in result["sources"].values()


def test_without_a_fallback_the_result_is_the_comptox_one() -> None:
    result = _run(StubComptox(weight=50.0, name="stub"), None)
    assert result["vapor_pressure"] is None and result["density"] is None


def test_one_gap_is_filled_and_comptox_values_are_untouched() -> None:
    comptox = StubComptox(weight=50.0, properties={"vapor_pressure": PRESSURE}, name="stub")
    fake = FakePubchem(offer(density=(0.5, "g/cm^3"), vapor_pressure=(99.0, "mmHg")))
    result = _run(comptox, fake)
    assert fake.calls == [(CAS, ("density",))]
    assert result["density"] == 0.5 and result["sources"]["density"] == "PubChem"
    assert (
        result["vapor_pressure"] == 11.0 and result["sources"]["vapor_pressure"] == "experimental"
    )
    assert result["molecular_weight"] == 50.0 and result["preferred_name"] == "stub"
    assert any("density" in w and "taken from PubChem" in w for w in result["warnings"])


def test_a_rejected_comptox_value_is_retried_and_its_warning_kept() -> None:
    bad: PropertyValue = {"value": 0.0, "unit": "mmHg", "source": "experimental"}
    comptox = StubComptox(weight=50.0, properties={"vapor_pressure": bad}, name="stub")
    result = _run(comptox, FakePubchem(offer(vapor_pressure=(4.0, "mmHg"))))
    assert result["vapor_pressure"] == 4.0 and result["sources"]["vapor_pressure"] == "PubChem"
    assert any("rejected value" in w for w in result["warnings"])


def test_pubchem_value_passes_the_plausibility_guard() -> None:
    result = _run(StubComptox(weight=50.0, name="x"), FakePubchem(offer(density=(-1.0, "g/cm^3"))))
    assert result["density"] is None
    assert any("density" in w and "rejected value" in w for w in result["warnings"])


def test_toxicity_values_and_the_name_are_never_asked_of_pubchem() -> None:
    fake = FakePubchem(
        offer(rfc=(1.0, "mg/m^3"), preferred_name=(1.0, "x")),
        fields=("preferred_name", "rfc", "rfd", "sf", "iur", "density"),
    )
    result = _run(StubComptox(weight=50.0, name=None), fake)
    assert fake.calls == [(CAS, ("density",))]
    assert result["rfc"] is None and result["preferred_name"] is None


def test_reason_for_a_field_pubchem_could_not_give_is_a_warning() -> None:
    fake = FakePubchem(PubchemCandidates(reasons={"density": "no usable density statement"}))
    result = _run(StubComptox(weight=50.0, name="x"), fake)
    assert result["density"] is None
    assert any("density: PubChem could not help: no usable" in w for w in result["warnings"])


def test_end_to_end_conversion_from_pubchem_spellings() -> None:
    body = record(
        cas=[CAS],
        pressure=[info("Vapor pressure, kPa at 20 °C: 1")],
        density=[info("500", "kg/cu m")],
    )
    result = _run(StubComptox(weight=50.0, name="x"), _real(body))
    assert result["vapor_pressure"] == pytest.approx(7.50062, rel=1e-4)
    assert result["sources"]["vapor_pressure"] == "PubChem"
    assert result["density"] == pytest.approx(0.5)


def test_end_to_end_density_in_pubchem_spelling() -> None:
    body = record(cas=[CAS], density=[info("Density, kg/cu m: 500")])
    result = _run(StubComptox(weight=50.0, name="x"), _real(body))
    assert result["density"] == pytest.approx(0.5)


def test_end_to_end_incompatible_unit_leaves_the_field_none_with_a_warning() -> None:
    body = record(cas=[CAS], pressure=[info("7 g/cu cm at 25 °C")])
    result = _run(StubComptox(weight=50.0, name="x"), _real(body))
    assert result["vapor_pressure"] is None
    assert any("vapor_pressure" in w and "does not convert" in w for w in result["warnings"])


def test_end_to_end_unclear_statements_are_not_used() -> None:
    body = record(cas=[CAS], pressure=[info("1-2 mmHg at 25 °C"), info("> 3 mmHg at 25 °C")])
    assert _run(StubComptox(weight=50.0, name="x"), _real(body))["vapor_pressure"] is None


def test_pubchem_down_gives_the_comptox_result_and_a_warning() -> None:
    url = SETTINGS.name_url(CAS)
    down = PubchemLookup(
        FakeJson({url: HttpRequestError("failed after 3 attempts", 503)}),
        SETTINGS,
        ALIASES,
    )
    comptox = StubComptox(weight=50.0, name="x")
    without = _run(comptox, None)
    result = _run(comptox, down)
    ignored = {"warnings", "occupational_limits"}
    assert {k: v for k, v in result.items() if k not in ignored} == {
        k: v for k, v in without.items() if k not in ignored
    }
    assert any(
        "PubChem could not help" in w and "could not be reached" in w for w in result["warnings"]
    )
    limits = result["occupational_limits"]
    assert limits["oel_twa_mg_m3"] is None and limits["oel_source"] is None
    assert any("PubChem limits unavailable" in w for w in limits["warnings"])


def test_unconfirmed_match_is_not_used() -> None:
    body = record(cas=[OTHER_CAS], density=[info("Density, kg/cu m: 500")])
    result = _run(StubComptox(weight=50.0, name="x"), _real(body))
    assert result["density"] is None
    assert any("not confirmed" in w for w in result["warnings"])


def test_cas_unknown_to_comptox_but_confirmed_by_pubchem() -> None:
    body = record(
        cas=[CAS],
        weight=[info("60", "g/mol")],
        density=[info("Density, g/cu cm: 0.5")],
    )
    result = _run(StubComptox(), _real(body))
    assert result["molecular_weight"] == 60.0 and result["density"] == 0.5
    assert result["sources"] == {"molecular_weight": "PubChem", "density": "PubChem"}
    assert result["preferred_name"] is None
    assert result["rfc"] is None and result["iur"] is None
    assert any("could not be resolved in CompTox" in w for w in result["warnings"])


def test_cas_unknown_to_both_stays_unresolved() -> None:
    result = _run(StubComptox(), PubchemLookup(FakeJson({}), SETTINGS, ALIASES))
    values = dict(result)
    assert all(values[k] is None for k in ("molecular_weight", "vapor_pressure", "density"))
    assert result["sources"] == {}


def test_invalid_cas_never_reaches_pubchem() -> None:
    fake = FakePubchem()
    result = _run(StubComptox(), fake, cas="not-a-cas")
    assert fake.calls == [] and result["molecular_weight"] is None
    assert any("not valid" in w for w in result["warnings"])


def test_missing_comptox_key_raises_before_any_pubchem_request() -> None:
    fake = FakePubchem(offer(density=(1.0, "g/cm^3")))
    comptox = ComptoxLookup(environ={})
    with pytest.raises(RuntimeError, match=get_comptox_settings().api_key_env_var):
        _run(comptox, fake)
    assert fake.calls == []


def test_mutating_a_result_does_not_change_the_next_one() -> None:
    fake = FakePubchem(offer(density=(0.5, "g/cm^3")))
    comptox = StubComptox(weight=50.0, name="x")
    first = _run(comptox, fake)
    first["sources"]["density"] = "tampered"
    first["warnings"].append("tampered")
    second = _run(comptox, fake)
    assert second["sources"]["density"] == "PubChem" and "tampered" not in second["warnings"]


def test_median_of_several_statements_is_reported_in_the_warning() -> None:
    body = record(cas=[CAS], pressure=[info("6 mmHg at 20 °C"), info("8 mmHg at 25 °C")])
    result = _run(StubComptox(weight=50.0, name="x"), _real(body))
    assert result["vapor_pressure"] == 7.0
    assert any("median of 2 statements" in w for w in result["warnings"])


def test_a_supplied_molecular_weight_reaches_the_limits_before_they_are_read() -> None:
    from tests.tools.informatics.test_properties import _answers  # pyright: ignore[reportPrivateUsage]

    fake = FakePubchem()
    answers = _answers(supplied={"molecular_weight:71-43-2": 78.0})
    lookup_chemical_properties(
        "71-43-2",
        StubComptox(weight=None, name="x"),
        get_comptox_settings(),
        get_unit_settings().aliases,
        fake,
        inputs=answers,
    )
    assert fake.limit_calls == [("71-43-2", 78.0)]


def test_a_found_molecular_weight_is_not_replaced_by_a_supplied_one() -> None:
    from tests.tools.informatics.test_properties import _answers  # pyright: ignore[reportPrivateUsage]

    fake = FakePubchem()
    lookup_chemical_properties(
        "71-43-2",
        StubComptox(weight=50.0, name="x"),
        get_comptox_settings(),
        get_unit_settings().aliases,
        fake,
        inputs=_answers(supplied={"molecular_weight:71-43-2": 78.0}),
    )
    assert fake.limit_calls == [("71-43-2", 50.0)]
