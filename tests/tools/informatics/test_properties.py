"""Tests for fetch_chemical_properties (no network, synthetic payloads)."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from config.loader import (
    ComptoxSettings,
    MolecularWeightSpec,
    get_comptox_settings,
    get_unit_settings,
)
from config.user_values import get_user_value_settings
from tests.tools.informatics.pubchem_fakes import FakePubchem
from tools.informatics import properties
from tools.informatics.helpers.comptox import ComptoxLookup
from tools.informatics.helpers.pubchem import PubchemFallback
from tools.informatics.helpers.pubchem.limits import empty_limits
from tools.informatics.properties import fetch_chemical_properties, lookup_chemical_properties
from tools.schemas import ChemicalProperties
from tools.user_values import UserValueInputs

CAS = "71-43-2"
DTX = "DTXSID0"
ENV = {get_comptox_settings().api_key_env_var: "test-key"}  # pragma: allowlist secret
FIELDS = (
    "preferred_name",
    "molecular_weight",
    "vapor_pressure",
    "density",
    "rfd",
    "rfc",
    "sf",
    "iur",
)


def _prop(
    name: str,
    unit: str,
    value: float | None,
    predicted: float | None = None,
) -> dict[str, object]:
    return {
        "propName": name,
        "unit": unit,
        "experimentalMedian": value,
        "predictedMedian": predicted,
    }


def _tox(
    type_: str,
    value: float,
    unit: str,
    route: str,
    source: str = "SRC",
    effect: str = "-",
    assessment: str = "-",
) -> dict[str, object]:
    return {
        "toxicologicalEffect": effect,
        "riskAssessmentClass": assessment,
        "dtxsid": DTX,
        "toxvalType": type_,
        "toxvalNumeric": value,
        "toxvalUnits": unit,
        "exposureRoute": route,
        "source": source,
    }


# Reported in units that differ from the targets, so conversion is exercised.
FULL_PROPS = [
    _prop("Vapor Pressure", "Pa", 133.322387415),  # = 1 mmHg
    _prop("Density", "kg/m^3", None, predicted=1000.0),  # = 1 g/cm^3, predicted
]
FULL_TOX = [
    _tox("RfD", 0.5, "mg/kg-day", "oral"),
    _tox("RfC", 2500.0, "ug/m3", "inhalation"),  # = 2.5 mg/m^3
    _tox("cancer slope factor", 4.0, "(mg/kg-day)-1", "oral"),
    _tox("cancer unit risk", 2.0, "(mg/m3)-1", "inhalation"),  # = 0.002 per ug/m^3
]


def _run(
    cas: str = CAS,
    *,
    props: object = FULL_PROPS,
    tox: object = FULL_TOX,
    mass: object = 12.5,
    known: bool = True,
    name: str | None = "Benzene",
    env: dict[str, str] | None = None,
    settings: ComptoxSettings | None = None,
    inputs: UserValueInputs | None = None,
) -> tuple[ChemicalProperties, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if "chemical/detail" in path:
            return httpx.Response(200, json={"dtxsid": DTX, "averageMass": mass})
        if "search/equal" in path:
            if not known:
                body = {"detail": "Searched by CASRN: Found 0 results for 'x'."}
                return httpx.Response(400, json=body)
            requested = path.rsplit("/", 1)[-1]  # the hyphenated CAS the helper asked for
            entry = {"dtxsid": DTX, "casrn": requested, "searchName": "CAS-RN"}
            if name is not None:
                entry["preferredName"] = name
            return httpx.Response(200, json=[entry])
        if "property/summary" in path:
            return httpx.Response(200, json=props)
        return httpx.Response(200, json=tox)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    settings = settings or get_comptox_settings()
    comptox = ComptoxLookup(
        settings,
        client,
        sleep=lambda _: None,
        environ=ENV if env is None else env,
    )
    aliases = get_unit_settings().aliases
    result = lookup_chemical_properties(cas, comptox, settings, aliases, inputs=inputs)
    return result, requests


def _field(result: ChemicalProperties, name: str) -> float | None:
    value = dict(result)[name]
    assert value is None or isinstance(value, float)
    return value


def test_schema() -> None:
    assert fetch_chemical_properties.name == "fetch_chemical_properties"
    assert set(fetch_chemical_properties.args) == {"cas_number"}  # config is injected, not asked
    description = fetch_chemical_properties.description
    for field in FIELDS:
        assert field in description
    for unit in ("g/mol", "mmHg", "g/cm^3", "mg/(kg*day)", "mg/m^3", "(ug/m^3)^-1"):
        assert unit in description
    assert "warnings" in description
    assert "missing" not in description  # read by the confirmation node, not the model
    assert "conservative" in description
    assert "toxicity_details" in description
    assert "exposure_route" in description


def test_all_values_converted_to_target_units() -> None:
    result, _ = _run()
    assert _field(result, "molecular_weight") == pytest.approx(12.5)
    assert _field(result, "vapor_pressure") == pytest.approx(1.0)
    assert _field(result, "density") == pytest.approx(1.0)
    assert _field(result, "rfd") == pytest.approx(0.5)
    assert _field(result, "rfc") == pytest.approx(2.5)
    assert _field(result, "sf") == pytest.approx(4.0)
    assert _field(result, "iur") == pytest.approx(0.002)
    assert result["warnings"] == []


def test_the_name_is_comptoxs_with_its_source_or_none_with_a_warning() -> None:
    result, _ = _run()
    assert (
        result["preferred_name"] == "Benzene" and result["sources"]["preferred_name"] == "CompTox"
    )
    result, _ = _run(name=None)
    assert result["preferred_name"] is None and "preferred_name" not in result["sources"]
    assert any(w.startswith("preferred_name: CompTox gave no name") for w in result["warnings"])
    result, _ = _run(known=False)
    assert result["preferred_name"] is None and "preferred_name" not in result["sources"]


def test_sources_reported() -> None:
    result, _ = _run()
    assert result["sources"] == {
        "preferred_name": "CompTox",
        "molecular_weight": "CompTox",
        "vapor_pressure": "experimental",
        "density": "predicted",
        "rfd": "SRC",
        "rfc": "SRC",
        "sf": "SRC",
        "iur": "SRC",
    }


def test_only_comptox_is_contacted_by_cas() -> None:
    _, requests = _run()
    assert {r.url.host for r in requests} == {"comptox.epa.gov"}
    assert requests[0].url.path.endswith(f"/search/equal/{CAS}")


def test_bare_number_cas_is_accepted() -> None:
    result, requests = _run("71432")
    assert _field(result, "rfc") == pytest.approx(2.5)
    assert requests[0].url.path.endswith(f"/search/equal/{CAS}")


def test_incompatible_unit_is_none_with_warning() -> None:
    props = [_prop("Vapor Pressure", "mmHg", 2.0), _prop("Density", "mmHg", 3.0)]
    result, _ = _run(props=props)
    assert result["density"] is None
    assert "density" not in result["sources"]
    assert any("density" in w and "mmHg" in w and "g/cm^3" in w for w in result["warnings"])
    assert _field(result, "vapor_pressure") == pytest.approx(2.0)
    assert _field(result, "rfc") == pytest.approx(2.5)


def test_unknown_unit_is_none_with_warning() -> None:
    tox = [_tox("RfC", 1.0, "furlongs", "inhalation"), *FULL_TOX[:1]]
    result, _ = _run(tox=tox)
    assert result["rfc"] is None
    assert any(w.startswith("rfc:") and "furlongs" in w for w in result["warnings"])
    assert _field(result, "rfd") == pytest.approx(0.5)


def test_missing_value_warns() -> None:
    result, _ = _run(tox=[t for t in FULL_TOX if t["toxvalType"] != "cancer unit risk"])
    assert result["iur"] is None
    assert "iur: not found in CompTox" in result["warnings"]
    assert _field(result, "rfc") == pytest.approx(2.5)


def test_conservative_value_is_returned() -> None:
    tox = [
        _tox("cancer slope factor", 0.015, "(mg/kg-day)-1", "oral"),
        _tox("cancer slope factor", 0.055, "(mg/kg-day)-1", "oral"),
        _tox("RfC", 0.03, "mg/m3", "inhalation"),
        _tox("RfC", 0.01, "mg/m3", "inhalation"),
    ]
    result, _ = _run(tox=tox)
    assert _field(result, "sf") == pytest.approx(0.055)
    assert _field(result, "rfc") == pytest.approx(0.01)


def test_wrong_route_is_not_returned_as_oral_slope_factor() -> None:
    tox = [_tox("cancer slope factor", 9.0, "(mg/kg-day)-1", "inhalation")]
    result, _ = _run(tox=tox)
    assert result["sf"] is None
    assert "sf: not found in CompTox" in result["warnings"]


@pytest.mark.parametrize("mass", [None, "12.5", True])
def test_missing_or_unusable_mass_keeps_comptox_values(mass: object) -> None:
    result, _ = _run(mass=mass)
    assert result["molecular_weight"] is None
    assert "molecular_weight" not in result["sources"]
    assert "molecular_weight: not found in CompTox" in result["warnings"]
    assert _field(result, "rfc") == pytest.approx(2.5)


def test_molecular_weight_is_converted_from_the_configured_unit() -> None:
    settings = replace(
        get_comptox_settings(),
        molecular_weight=MolecularWeightSpec("averageMass", "kg/mol", "g/mol"),
    )
    result, _ = _run(mass=0.0125, settings=settings)  # 0.0125 kg/mol = 12.5 g/mol
    assert _field(result, "molecular_weight") == pytest.approx(12.5)


def test_molecular_weight_in_an_incompatible_unit_is_rejected() -> None:
    settings = replace(
        get_comptox_settings(),
        molecular_weight=MolecularWeightSpec("averageMass", "mmHg", "g/mol"),
    )
    result, _ = _run(mass=12.5, settings=settings)
    assert result["molecular_weight"] is None
    assert "molecular_weight" not in result["sources"]
    assert any(w.startswith("molecular_weight:") and "mmHg" in w for w in result["warnings"])
    assert _field(result, "rfc") == pytest.approx(2.5)


@pytest.mark.parametrize("mass", [0.0, -3.0])
def test_non_positive_mass_is_rejected(mass: float) -> None:
    result, _ = _run(mass=mass)
    assert result["molecular_weight"] is None
    assert any(w.startswith("molecular_weight: rejected value") for w in result["warnings"])
    assert _field(result, "rfc") == pytest.approx(2.5)


def test_no_comptox_data_keeps_molecular_weight() -> None:
    result, _ = _run(props=[], tox=[])
    assert _field(result, "molecular_weight") is not None
    assert all(_field(result, f) is None for f in FIELDS[2:])  # the name and mass are kept
    assert result["preferred_name"] == "Benzene"
    assert len(result["warnings"]) == 1
    assert "no CompTox data retrieved" in result["warnings"][0]


def test_no_mass_and_no_data_is_unresolved() -> None:
    result, _ = _run(props=[], tox=[], mass=None)
    assert all(_field(result, f) is None for f in FIELDS)
    assert len(result["warnings"]) == 1
    assert "could not be resolved" in result["warnings"][0]


def test_unknown_cas_returns_all_none_with_warning() -> None:
    result, requests = _run("50-00-0", known=False)
    assert all(_field(result, f) is None for f in FIELDS)
    assert result["sources"] == {}
    assert "could not be resolved" in result["warnings"][0]
    assert len(requests) == 1


@pytest.mark.parametrize("cas", ["", "  ", "71-43-3", "0-00-0", "not a cas", "71-43-2; x"])
def test_invalid_cas_makes_no_request_and_needs_no_key(cas: str) -> None:
    result, requests = _run(cas, env={})
    assert all(_field(result, f) is None for f in FIELDS)
    assert result["sources"] == {}
    assert "could not be resolved" in result["warnings"][0]
    assert requests == []


def test_missing_api_key_raises_for_valid_cas() -> None:
    with pytest.raises(RuntimeError, match=get_comptox_settings().api_key_env_var):
        _run(env={})


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_non_positive_value_is_rejected(value: float) -> None:
    tox = [_tox("RfC", value, "mg/m3", "inhalation"), *FULL_TOX[:1]]
    result, _ = _run(tox=tox)
    assert result["rfc"] is None
    assert "rfc" not in result["sources"]
    assert any(w.startswith("rfc: rejected value") for w in result["warnings"])
    assert _field(result, "rfd") == pytest.approx(0.5)


def test_non_positive_property_is_rejected() -> None:
    result, _ = _run(props=[_prop("Density", "g/cm^3", 0.0)])
    assert result["density"] is None
    assert any(w.startswith("density: rejected value") for w in result["warnings"])


def test_caller_cannot_alter_later_results() -> None:
    comptox, settings, aliases = _services_for_reuse()
    first = lookup_chemical_properties(CAS, comptox, settings, aliases)
    first["sources"].clear()
    first["warnings"].append("tampered")
    second = lookup_chemical_properties(CAS, comptox, settings, aliases)
    assert "rfc" in second["sources"]
    assert "tampered" not in second["warnings"]


def _services_for_reuse() -> tuple[ComptoxLookup, ComptoxSettings, dict[str, str]]:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "chemical/detail" in path:
            return httpx.Response(200, json={"dtxsid": DTX, "averageMass": 12.5})
        if "search/equal" in path:
            entry = {"dtxsid": DTX, "casrn": CAS, "searchName": "CAS-RN"}
            return httpx.Response(200, json=[entry])
        if "property/summary" in path:
            return httpx.Response(200, json=FULL_PROPS)
        return httpx.Response(200, json=FULL_TOX)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    settings = get_comptox_settings()
    comptox = ComptoxLookup(settings, client, sleep=lambda _: None, environ=ENV)
    return comptox, settings, get_unit_settings().aliases


def test_tool_invoke_delegates_with_default_services(monkeypatch: pytest.MonkeyPatch) -> None:
    services = properties._Services(  # pyright: ignore[reportPrivateUsage]
        comptox=ComptoxLookup(),
        settings=get_comptox_settings(),
        aliases={},
        pubchem=FakePubchem(),
    )
    expected: ChemicalProperties = {
        "preferred_name": None,
        "molecular_weight": 1.0,
        "vapor_pressure": None,
        "density": None,
        "rfd": None,
        "rfc": None,
        "sf": None,
        "iur": None,
        "sources": {},
        "toxicity_details": {},
        "warnings": ["x"],
        "missing": [],
        "occupational_limits": empty_limits("not looked up"),
    }
    seen: list[str] = []

    def fake_lookup(
        cas: str,
        comptox: ComptoxLookup,
        settings: ComptoxSettings,
        aliases: dict[str, str],
        pubchem: PubchemFallback | None,
        inputs: UserValueInputs | None = None,
    ) -> ChemicalProperties:
        assert inputs is not None
        assert (comptox, settings, aliases, pubchem) == (
            services.comptox,
            services.settings,
            services.aliases,
            services.pubchem,
        )
        seen.append(cas)
        return expected

    monkeypatch.setattr(properties, "_services", lambda: services)
    monkeypatch.setattr(properties, "lookup_chemical_properties", fake_lookup)
    assert fetch_chemical_properties.invoke({"cas_number": CAS}) == expected
    assert seen == [CAS]


def test_toxicity_details_explain_route_and_endpoint() -> None:
    tox = [
        _tox("RfD", 0.5, "mg/kg-day", "oral", "IRIS", "reduced lymphocyte count", "Non-cancer"),
        _tox("RfC", 2500.0, "ug/m3", "not specified", "PA", "-", "Non-cancer"),
        _tox("cancer slope factor", 4.0, "(mg/kg-day)-1", "oral", "IRIS", "leukemia", "Cancer"),
        _tox("cancer unit risk", 2.0, "(mg/m3)-1", "inhalation", "IRIS", "leukemia", "Cancer"),
    ]
    result, _ = _run(tox=tox)
    assert result["toxicity_details"] == {
        "rfd": {
            "source": "IRIS",
            "exposure_route": "oral",
            "route_reported": "oral",
            "endpoint": "reduced lymphocyte count",
            "assessment": "non-cancer",
        },
        "rfc": {
            "source": "PA",
            "exposure_route": "inhalation",
            "route_reported": "not specified",
            "endpoint": None,
            "assessment": "non-cancer",
        },
        "sf": {
            "source": "IRIS",
            "exposure_route": "oral",
            "route_reported": "oral",
            "endpoint": "leukemia",
            "assessment": "cancer",
        },
        "iur": {
            "source": "IRIS",
            "exposure_route": "inhalation",
            "route_reported": "inhalation",
            "endpoint": "leukemia",
            "assessment": "cancer",
        },
    }


def test_details_only_for_toxicity_values_that_have_a_value() -> None:
    tox = [_tox("RfD", 0.5, "mg/kg-day", "oral"), _tox("RfC", 0.0, "mg/m3", "inhalation")]
    result, _ = _run(tox=tox)
    assert set(result["toxicity_details"]) == {"rfd"}  # rfc rejected, sf/iur absent
    assert set(result["toxicity_details"]) <= set(result["sources"])


def test_details_empty_without_toxicity_data() -> None:
    result, _ = _run(tox=[])
    assert result["toxicity_details"] == {}


def test_details_use_the_applied_route_from_configuration() -> None:
    result, _ = _run()
    routes = {k: v["exposure_route"] for k, v in result["toxicity_details"].items()}
    assert routes == {"rfd": "oral", "rfc": "inhalation", "sf": "oral", "iur": "inhalation"}


def test_caller_cannot_alter_cached_details() -> None:
    comptox, settings, aliases = _services_for_reuse()
    first = lookup_chemical_properties(CAS, comptox, settings, aliases)
    first["toxicity_details"]["rfd"]["endpoint"] = "tampered"
    first["toxicity_details"].clear()
    second = lookup_chemical_properties(CAS, comptox, settings, aliases)
    assert second["toxicity_details"]["rfd"]["endpoint"] != "tampered"
    assert "rfd" in second["toxicity_details"]


NO_IUR = [t for t in FULL_TOX if t["toxvalType"] != "cancer unit risk"]


def _answers(
    supplied: dict[str, float] | None = None,
    declined: frozenset[str] = frozenset(),
) -> UserValueInputs:
    return UserValueInputs(
        settings=get_user_value_settings(),
        aliases=get_unit_settings().aliases,
        supplied=supplied or {},
        declined=declined,
    )


def test_missing_iur_is_listed_for_the_user_with_its_units_and_range() -> None:
    result, _ = _run(tox=NO_IUR)
    entries = {e["quantity"]: e for e in result["missing"]}
    assert set(entries) == {"iur", "oel_twa"}  # no limit was looked up in this run
    entry = entries["iur"]
    assert entry["entry_id"] == f"iur:{CAS}"
    assert entry["accepted_units"][0] == "1/(ug/m^3)"
    assert "1/(mg/m^3)" in entry["accepted_units"]
    assert entry["minimum"] < entry["maximum"]
    assert "cancer" in entry["purpose"]


def test_every_value_no_source_has_is_asked_for() -> None:
    result, _ = _run(props=[], tox=[])
    asked = {e["quantity"] for e in result["missing"]}
    assert asked == {"rfc", "iur", "vapor_pressure", "density", "oel_twa"}  # the weight was found


def test_each_asked_value_says_what_it_is_for_and_what_it_is_not_used_for() -> None:
    result, _ = _run(props=[], tox=[], mass=None)
    purposes = {e["quantity"]: e["purpose"] for e in result["missing"]}
    assert "molecular_weight" in purposes and "ppm" in purposes["molecular_weight"]
    assert "vapor generation" in purposes["vapor_pressure"]
    assert "not used in an equation" in purposes["density"]
    assert "occupational limit" in purposes["oel_twa"]


def test_a_supplied_occupational_limit_is_used_labelled_and_no_longer_asked() -> None:
    answers = _answers(supplied={f"oel_twa:{CAS}": 3.0})
    result, _ = _run(inputs=answers)
    limits = result["occupational_limits"]
    assert limits["oel_twa_mg_m3"] == pytest.approx(3.0)
    assert (
        limits["oel_source"] == "user-provided" and result["sources"]["oel_twa"] == "user-provided"
    )
    assert all(e["quantity"] != "oel_twa" for e in result["missing"])


def test_a_supplied_limit_in_micrograms_is_converted_and_a_bad_one_is_refused() -> None:
    ok, _ = _run(inputs=_answers(supplied={f"oel_twa:{CAS}": 3000.0}))
    assert ok["occupational_limits"]["oel_twa_mg_m3"] is not None
    bad, _ = _run(inputs=_answers(supplied={f"oel_twa:{CAS}": -1.0}))
    assert bad["occupational_limits"]["oel_twa_mg_m3"] is None
    assert "oel_twa" in {e["quantity"] for e in bad["missing"]}


def test_found_benchmark_is_never_listed_or_replaced() -> None:
    answers = _answers(supplied={f"rfc:{CAS}": 9.0})
    result, _ = _run(inputs=answers)
    assert _field(result, "rfc") == pytest.approx(2.5)
    assert result["sources"]["rfc"] != "user-provided"
    assert all(e["quantity"] != "rfc" for e in result["missing"])


def test_supplied_missing_benchmark_is_used_and_labelled() -> None:
    answers = _answers(supplied={f"iur:{CAS}": 2e-6})
    result, _ = _run(tox=NO_IUR, inputs=answers)
    assert _field(result, "iur") == pytest.approx(2e-6)
    assert result["sources"]["iur"] == "user-provided"
    assert not any(w.startswith("iur:") for w in result["warnings"])
    assert [e["quantity"] for e in result["missing"]] == ["oel_twa"]


def test_declined_benchmark_stays_none_with_its_warning() -> None:
    answers = _answers(declined=frozenset({f"iur:{CAS}"}))
    result, _ = _run(tox=NO_IUR, inputs=answers)
    assert _field(result, "iur") is None
    assert "iur: not found in CompTox" in result["warnings"]
    assert [e["quantity"] for e in result["missing"]] == ["oel_twa"]


def test_supplied_value_is_rechecked_and_out_of_range_is_not_used() -> None:
    answers = _answers(supplied={f"iur:{CAS}": -1.0})
    result, _ = _run(tox=NO_IUR, inputs=answers)
    assert _field(result, "iur") is None
    assert [e["quantity"] for e in result["missing"]] == ["iur", "oel_twa"]


def test_a_value_for_another_chemical_is_not_used() -> None:
    answers = _answers(supplied={"iur:50-00-0": 2e-6})
    result, _ = _run(tox=NO_IUR, inputs=answers)
    assert _field(result, "iur") is None
