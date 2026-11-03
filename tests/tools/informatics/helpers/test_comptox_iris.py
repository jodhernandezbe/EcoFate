"""Tests for the IRIS endpoint ranked ahead of ToxVal (no network, synthetic payloads)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx

from tests.tools.informatics.helpers.test_comptox_retry import (
    CAS,
    CHEM,
    DTX,
    RFC,
    SEARCH,
    TOXVAL,
    Service,
)
from tools.informatics.helpers.comptox import ComptoxLookup

IRIS = "/ctx-api/hazard/iris"
IRIS_SOURCE = "EPA IRIS: IRIS (CompTox IRIS endpoint, last significant revision 2020-01-01)"
RECORD = {
    "dtxsid": DTX,
    "rfcChronic": "2 x 10 -1 mg/m3",
    "rfdChronic": "4 x 10 -3 mg/kg-day",
    "criticalEffectsSystems": "Respiratory\nNervous system\n",
    "lastSignificantRevision": "2020-01-01",
    "tumorSite": "Lung",
}
TOXVAL_IRIS_RFC = {**RFC, "toxvalNumeric": 0.2, "toxvalUnits": "mg/m3"}  # agrees with RECORD
CANCER = {
    "dtxsid": DTX,
    "toxvalType": "cancer unit risk",
    "toxvalNumeric": 0.5,
    "toxvalUnits": "(ug/m3)-1",
    "exposureRoute": "inhalation",
    "source": "EPA IRIS: IRIS",
}


def _ok(body: object) -> httpx.Response:
    return httpx.Response(200, json=body)


def _lookup(
    iris: list[httpx.Response | Exception],
    toxval: Sequence[Mapping[str, object]] | None = None,
) -> tuple[Service, ComptoxLookup]:
    service = Service({SEARCH: [_ok(CHEM)], TOXVAL: [_ok(toxval or [])], IRIS: iris})
    return service, service.lookup(with_iris=True)


def test_the_endpoint_value_is_used_with_its_context() -> None:
    _, lookup = _lookup([_ok([RECORD])])
    rfc = lookup.get_toxicity_values(CAS)["rfc"]
    assert rfc == {
        "value": 0.2,
        "unit": "mg/m3",
        "source": IRIS_SOURCE,
        "route": "inhalation",
        "endpoint": "Respiratory, Nervous system",
        "assessment": "non-cancer",
    }
    assert lookup.get_toxicity_values(CAS)["rfd"]["unit"] == "mg/kg-day"
    assert lookup.get_toxicity_values(CAS)["rfd"]["route"] == "oral"


def test_the_endpoint_ranks_ahead_of_every_toxval_source() -> None:
    other = {**RFC, "source": "Alaska DEC", "toxvalNumeric": 0.001}
    _, lookup = _lookup([_ok([RECORD])], [other])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.2


def test_without_a_revision_date_the_source_has_none() -> None:
    record = {k: v for k, v in RECORD.items() if k != "lastSignificantRevision"}
    _, lookup = _lookup([_ok([record])])
    assert (
        lookup.get_toxicity_values(CAS)["rfc"]["source"] == "EPA IRIS: IRIS (CompTox IRIS endpoint)"
    )


def test_toxval_is_used_when_the_endpoint_has_no_record() -> None:
    _, lookup = _lookup([_ok([])], [RFC])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5


def test_toxval_is_used_when_the_endpoint_has_no_chronic_value() -> None:
    record = {"dtxsid": DTX, "rfcSubchronic": "1 mg/m3", "rfcChronic": "-"}
    _, lookup = _lookup([_ok([record])], [RFC])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    assert lookup.get_toxicity_notes(CAS) == []


def test_subchronic_values_are_never_used() -> None:
    record = {"dtxsid": DTX, "rfcSubchronic": "1 mg/m3", "rfdSubchronic": "1 mg/kg-day"}
    _, lookup = _lookup([_ok([record])])
    assert lookup.get_toxicity_values(CAS) == {}


def test_cancer_values_still_come_from_toxval() -> None:
    _, lookup = _lookup([_ok([RECORD])], [CANCER])
    result = lookup.get_toxicity_values(CAS)
    assert result["iur"]["value"] == 0.5 and result["iur"]["source"] == "EPA IRIS: IRIS"
    assert "sf" not in result


def test_unreadable_text_falls_back_to_toxval_with_a_note() -> None:
    record = {**RECORD, "rfcChronic": "1-2 mg/m3"}
    _, lookup = _lookup([_ok([record])], [RFC])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    assert lookup.get_toxicity_notes(CAS) == [
        "rfc: IRIS endpoint text '1-2 mg/m3' cannot be read exactly",
    ]


def test_agreeing_values_give_no_note() -> None:
    _, lookup = _lookup([_ok([RECORD])], [TOXVAL_IRIS_RFC])
    lookup.get_toxicity_values(CAS)
    assert lookup.get_toxicity_notes(CAS) == []


def test_disagreeing_values_use_the_endpoint_and_name_both() -> None:
    _, lookup = _lookup([_ok([RECORD])], [{**TOXVAL_IRIS_RFC, "toxvalNumeric": 0.35}])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.2
    (note,) = lookup.get_toxicity_notes(CAS)
    assert "0.2 mg/m3" in note and "0.35 mg/m3" in note and "ToxVal" in note


def test_another_source_is_not_compared() -> None:
    other = {**TOXVAL_IRIS_RFC, "source": "Alaska DEC", "toxvalNumeric": 9.0}
    _, lookup = _lookup([_ok([RECORD])], [other])
    lookup.get_toxicity_values(CAS)
    assert lookup.get_toxicity_notes(CAS) == []


def test_a_record_for_another_chemical_is_ignored() -> None:
    _, lookup = _lookup([_ok([{**RECORD, "dtxsid": "DTXSID9"}])], [RFC])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5


def test_endpoint_failure_keeps_toxval_and_is_not_cached() -> None:
    service, _ = _lookup([httpx.Response(500), _ok([RECORD])], [RFC])
    lookup = service.lookup(retries=0, with_iris=True)
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.2
    assert service.count(IRIS) == 2


def test_endpoint_miss_is_final_and_cached() -> None:
    service, lookup = _lookup([httpx.Response(404)], [RFC])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    lookup.get_toxicity_values(CAS)
    assert service.count(IRIS) == 1


def test_malformed_endpoint_answer_is_not_cached() -> None:
    service, lookup = _lookup([_ok({"detail": "oops"})], [RFC])
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    lookup.get_toxicity_values(CAS)
    assert service.count(IRIS) == 2


def test_the_endpoint_is_not_asked_when_it_is_not_configured() -> None:
    service = Service({SEARCH: [_ok(CHEM)], TOXVAL: [_ok([RFC])]})
    assert service.lookup().get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    assert service.count(IRIS) == 0
