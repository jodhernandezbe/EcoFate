"""Tests for tools.informatics.helpers.comptox (no network, synthetic payloads)."""

from __future__ import annotations

import json
import math
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from config.loader import ComptoxSettings, MolecularWeightSpec, PropertySpec, ToxicityValueSpec
from tools.credentials import COMPTOX_KEY
from tools.informatics.helpers.comptox import ComptoxLookup, tls_verification

CAS = "71-43-2"  # valid CAS format and check digit; the data below is synthetic
DTX = "DTXSID0"
MASS = 20.0  # synthetic average mass, g/mol
ENV = {"TEST_KEY_VAR": "test-key"}  # pragma: allowlist secret


def _settings(
    *extra: PropertySpec,
    tox_extra: tuple[ToxicityValueSpec, ...] = (),
) -> ComptoxSettings:
    return ComptoxSettings(
        base_url="https://ctx.test/api",
        dtxsid_by_cas_path="/c/{casrn}",
        detail_by_dtxsid_path="/d/{dtxsid}",
        properties_by_dtxsid_path="/p/{dtxsid}",
        toxval_by_dtxsid_path="/t/{dtxsid}",
        source_priority=("SRC_A", "SRC_B"),
        api_key_header="x-test-key",  # pragma: allowlist secret
        api_key_env_var="TEST_KEY_VAR",  # pragma: allowlist secret
        delay_seconds=0.5,
        timeout_seconds=1.0,
        max_retries=0,
        backoff_seconds=1.0,
        accept_expired_certificate=False,
        molecular_weight=MolecularWeightSpec("averageMass", "g/mol", "g/mol"),
        properties=(
            PropertySpec("vapor_pressure", "Vapor Pressure", "u"),
            PropertySpec("density", "Density", "u"),
            *extra,
        ),
        toxicity_values=(
            ToxicityValueSpec("rfd", ("RfD",), ("oral", "not specified"), "lowest", "u"),
            ToxicityValueSpec("rfc", ("RfC",), ("inhalation", "not specified"), "lowest", "u"),
            ToxicityValueSpec("sf", ("cancer slope factor",), ("oral",), "highest", "u"),
            ToxicityValueSpec("iur", ("cancer unit risk",), ("inhalation",), "highest", "u"),
            *tox_extra,
        ),
    )


def _entry(
    name: str,
    unit: object = "u",
    experimental: object = None,
    predicted: object = None,
) -> dict[str, object]:
    return {
        "propName": name,
        "unit": unit,
        "experimentalMedian": experimental,
        "predictedMedian": predicted,
    }


def _rec(
    type_: str,
    value: object = 1.0,
    unit: object = "u",
    source: object = "SRC_X",
    route: object = "oral",
    dtxsid: object = DTX,
    effect: object = "-",
    assessment: object = "-",
) -> dict[str, object]:
    return {
        "toxicologicalEffect": effect,
        "riskAssessmentClass": assessment,
        "dtxsid": dtxsid,
        "toxvalType": type_,
        "toxvalNumeric": value,
        "toxvalUnits": unit,
        "source": source,
        "exposureRoute": route,
    }


def _raw(body: object) -> str:
    """JSON text that may contain NaN/Infinity, which httpx's json= refuses to encode."""
    return json.dumps(body)


def _chem(cas: str = CAS, search: str = "CAS-RN", name: object = "Benzene") -> dict[str, object]:
    return {"dtxsid": DTX, "casrn": cas, "searchName": search, "preferredName": name}


def _detail(mass: object = MASS, dtxsid: object = DTX) -> dict[str, object]:
    return {"dtxsid": dtxsid, "averageMass": mass}


def _lookup(
    summary: object = (),
    tox: object = (),
    *,
    chem: object = None,
    chem_status: int = 200,
    detail: object = None,
    detail_status: int = 200,
    summary_status: int = 200,
    tox_status: int = 200,
    env: dict[str, str] | None = None,
    settings: ComptoxSettings | None = None,
    fail: Exception | None = None,
    sleeps: list[float] | None = None,
) -> tuple[ComptoxLookup, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if fail is not None:
            raise fail
        path = request.url.path
        if path.startswith("/api/c/"):
            requested = path.removeprefix("/api/c/")
            body = [_chem(requested)] if chem is None else chem
            if isinstance(body, str):
                return httpx.Response(chem_status, text=body)
            return httpx.Response(chem_status, json=body)
        if path.startswith("/api/d/"):
            body = _detail() if detail is None else detail
            if isinstance(body, str):
                return httpx.Response(detail_status, text=body)
            return httpx.Response(detail_status, json=body)
        if path.startswith("/api/p/"):
            if isinstance(summary, str):
                return httpx.Response(summary_status, text=summary)
            return httpx.Response(summary_status, json=summary)
        if isinstance(tox, str):
            return httpx.Response(tox_status, text=tox)
        return httpx.Response(tox_status, json=tox)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    record = sleeps if sleeps is not None else []
    lookup = ComptoxLookup(
        settings or _settings(),
        client,
        sleep=record.append,
        environ=ENV if env is None else env,
    )
    return lookup, requests


def _chem_requests(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in requests if r.url.path.startswith("/api/c/")]


# --- properties -----------------------------------------------------------------------------


def test_experimental_preferred_over_predicted() -> None:
    summary = [
        _entry("Vapor Pressure", "unit-a", experimental=1.5, predicted=9.0),
        _entry("Density", "unit-b", experimental=2.5, predicted=8.0),
    ]
    lookup, _ = _lookup(summary)
    assert lookup.get_properties(CAS) == {
        "vapor_pressure": {"value": 1.5, "unit": "unit-a", "source": "experimental"},
        "density": {"value": 2.5, "unit": "unit-b", "source": "experimental"},
    }


def test_predicted_fallback_and_unit_passthrough() -> None:
    lookup, _ = _lookup([_entry("Vapor Pressure", "mmHg", predicted=3.0)])
    assert lookup.get_properties(CAS) == {
        "vapor_pressure": {"value": 3.0, "unit": "mmHg", "source": "predicted"},
    }


def test_zero_experimental_is_a_value() -> None:
    lookup, _ = _lookup([_entry("Density", experimental=0.0, predicted=5.0)])
    assert lookup.get_properties(CAS)["density"]["value"] == 0.0


def test_missing_or_empty_properties_omitted() -> None:
    lookup, _ = _lookup([_entry("Vapor Pressure"), _entry("Boiling Point", experimental=1.0)])
    assert lookup.get_properties(CAS) == {}


@pytest.mark.parametrize(
    "entry",
    [
        _entry("Density", experimental=math.nan, predicted=math.inf),
        _entry("Density", experimental=True),
        _entry("Density", experimental="1.0"),
        _entry("Density", unit=None, experimental=1.0),
        _entry("Density", unit="  ", experimental=1.0),
    ],
)
def test_untrusted_property_values_are_ignored(entry: dict[str, object]) -> None:
    lookup, _ = _lookup(_raw([entry]))
    assert lookup.get_properties(CAS) == {}


def test_non_finite_experimental_falls_back_to_finite_predicted() -> None:
    lookup, _ = _lookup(_raw([_entry("Density", experimental=math.nan, predicted=2.0)]))
    assert lookup.get_properties(CAS)["density"]["source"] == "predicted"


def test_unconfigured_ignored_and_extra_configured_picked_up() -> None:
    summary = [_entry("Density", experimental=1.0), _entry("Melting Point", "c", experimental=7.0)]
    lookup, _ = _lookup(summary)
    assert set(lookup.get_properties(CAS)) == {"density"}
    extended, _ = _lookup(
        summary,
        settings=_settings(PropertySpec("melting_point", "Melting Point", "u")),
    )
    assert set(extended.get_properties(CAS)) == {"density", "melting_point"}


def test_requests_use_cas_path_header_and_delay() -> None:
    sleeps: list[float] = []
    lookup, requests = _lookup([_entry("Density", experimental=1.0)], sleeps=sleeps)
    lookup.get_properties(CAS)
    assert str(requests[0].url) == f"https://ctx.test/api/c/{CAS}"
    assert str(requests[1].url) == f"https://ctx.test/api/p/{DTX}"
    assert all(r.headers["x-test-key"] == "test-key" for r in requests)
    assert sleeps == [0.5, 0.5]


@pytest.mark.parametrize("payload", [{"not": "a list"}, "not json", [], [{"x": 1}], 7])
def test_malformed_summary_gives_nothing(payload: object) -> None:
    lookup, _ = _lookup(payload)
    assert lookup.get_properties(CAS) == {}


# --- CAS resolution -------------------------------------------------------------------------


@pytest.mark.parametrize("cas", ["", "   ", "71-43-3", "0-00-0", "71-43", "abc", "71-43-2; x"])
def test_invalid_or_blank_cas_makes_no_request_and_needs_no_key(cas: str) -> None:
    lookup, requests = _lookup(env={})
    assert lookup.get_properties(cas) == {}
    assert lookup.get_toxicity_values(cas) == {}
    assert lookup.get_molecular_weight(cas) is None
    assert requests == []


def test_bare_number_cas_is_looked_up_hyphenated() -> None:
    lookup, requests = _lookup([_entry("Density", experimental=1.0)])
    assert "density" in lookup.get_properties("71432")
    assert requests[0].url.path == f"/api/c/{CAS}"


def test_surrounding_whitespace_is_ignored() -> None:
    lookup, requests = _lookup()
    lookup.get_properties(f"  {CAS}\n")
    assert requests[0].url.path == f"/api/c/{CAS}"


def test_result_of_another_kind_is_rejected() -> None:
    trap = [_chem("68334-50-9", search="Substance_id")]
    lookup, requests = _lookup([_entry("Density", experimental=1.0)], chem=trap)
    assert lookup.get_properties(CAS) == {}
    assert lookup.get_molecular_weight(CAS) is None
    assert len(requests) == 1  # a definitive miss is cached; no further request


def test_cas_match_with_different_cas_is_rejected() -> None:
    lookup, _ = _lookup([_entry("Density", experimental=1.0)], chem=[_chem("50-00-0")])
    assert lookup.get_properties(CAS) == {}


def test_the_preferred_name_comes_with_the_match_from_the_same_request() -> None:
    lookup, requests = _lookup(chem=[_chem(name=" Benzene ")])
    assert lookup.get_preferred_name(CAS) == "Benzene"
    assert lookup.get_molecular_weight(CAS) == MASS
    assert sum(r.url.path.endswith(f"/{CAS}") for r in requests) == 1  # one CAS search


@pytest.mark.parametrize("name", [None, "", "  ", "-", 7, ["x"]])
def test_a_missing_or_unusable_name_leaves_the_match_usable_without_a_name(name: object) -> None:
    lookup, _ = _lookup(chem=[_chem(name=name)])
    assert lookup.get_preferred_name(CAS) is None
    assert lookup.get_molecular_weight(CAS) == MASS


def test_no_match_or_invalid_cas_gives_no_name() -> None:
    lookup, requests = _lookup(chem=[_chem("50-00-0")])
    assert lookup.get_preferred_name(CAS) is None
    assert lookup.get_preferred_name("not-a-cas") is None
    assert len(requests) == 1


def test_matching_entry_is_found_among_several() -> None:
    chem = [_chem("50-00-0"), _chem(CAS, search="Substance_id"), _chem(CAS)]
    lookup, requests = _lookup(chem=chem)
    assert lookup.get_molecular_weight(CAS) == MASS
    assert requests[1].url.path == f"/api/d/{DTX}"


@pytest.mark.parametrize(
    "entry",
    [
        {"casrn": CAS, "searchName": "CAS-RN"},
        {"dtxsid": "", "casrn": CAS, "searchName": "CAS-RN"},
        {"dtxsid": 5, "casrn": CAS, "searchName": "CAS-RN"},
    ],
)
def test_match_without_usable_dtxsid_is_rejected(entry: dict[str, object]) -> None:
    lookup, _ = _lookup([_entry("Density", experimental=1.0)], chem=[entry])
    assert lookup.get_properties(CAS) == {}


@pytest.mark.parametrize("chem", [{"not": "a list"}, "not json", 3])
def test_malformed_cas_response_is_a_transient_failure(chem: object) -> None:
    lookup, requests = _lookup(chem=chem)
    assert lookup.get_properties(CAS) == {}
    lookup.get_properties(CAS)
    assert len(requests) == 2


def test_empty_result_is_cached_as_no_match() -> None:
    lookup, requests = _lookup(chem=[])
    assert lookup.get_properties(CAS) == {}
    assert lookup.get_properties(CAS) == {}
    assert lookup.get_toxicity_values(CAS) == {}
    assert len(requests) == 1


def test_404_is_cached() -> None:
    lookup, requests = _lookup(chem={"error": "x"}, chem_status=404)
    assert lookup.get_properties(CAS) == {}
    lookup.get_properties(CAS)
    assert len(requests) == 1


def test_400_zero_results_is_a_cached_no_match() -> None:
    body = {"status": 400, "detail": "Searched by CASRN: Found 0 results for '71-43-2'."}
    lookup, requests = _lookup(chem=body, chem_status=400)
    assert lookup.get_properties(CAS) == {}
    lookup.get_properties(CAS)
    assert len(requests) == 1


@pytest.mark.parametrize("body", [{"detail": "Malformed request"}, "not json", ["x"]])
def test_other_400_is_not_cached(body: object) -> None:
    lookup, requests = _lookup(chem=body, chem_status=400)
    assert lookup.get_properties(CAS) == {}
    lookup.get_properties(CAS)
    assert len(requests) == 2


@pytest.mark.parametrize("env", [{}, {"TEST_KEY_VAR": "  "}])
def test_missing_api_key_raises_for_valid_cas_without_request(env: dict[str, str]) -> None:
    lookup, requests = _lookup(env=env)
    for call in (lookup.get_properties, lookup.get_toxicity_values, lookup.get_molecular_weight):
        with pytest.raises(RuntimeError, match="TEST_KEY_VAR"):
            call(CAS)
    assert requests == []


# --- molecular weight -----------------------------------------------------------------------


def test_get_molecular_weight_returns_average_mass() -> None:
    lookup, requests = _lookup(detail=_detail(78.5))
    assert lookup.get_molecular_weight(CAS) == 78.5
    assert str(requests[1].url) == f"https://ctx.test/api/d/{DTX}"
    assert all(r.headers["x-test-key"] == "test-key" for r in requests)


@pytest.mark.parametrize(
    "body",
    [
        {"dtxsid": DTX},
        _detail(None),
        _detail("20.0"),
        _detail(True),
        _detail(math.nan),
        _detail(math.inf),
        _detail([20.0]),
    ],
)
def test_unusable_mass_is_none_and_cached(body: dict[str, object]) -> None:
    lookup, requests = _lookup(detail=_raw(body), chem=[_chem()])
    assert lookup.get_molecular_weight(CAS) is None
    assert lookup.get_molecular_weight(CAS) is None
    assert len(requests) == 2  # chemical once, detail once


def test_configured_field_name_is_used() -> None:
    settings = replace(_settings(), molecular_weight=MolecularWeightSpec("otherMass", "u", "u"))
    detail = {"dtxsid": DTX, "averageMass": 1.0, "otherMass": 3.5}
    lookup, _ = _lookup(detail=detail, settings=settings)
    assert lookup.get_molecular_weight(CAS) == 3.5


def test_detail_for_another_chemical_is_ignored_and_retried() -> None:
    lookup, requests = _lookup(detail=_detail(dtxsid="DTXSID_OTHER"))
    assert lookup.get_molecular_weight(CAS) is None
    lookup.get_molecular_weight(CAS)
    assert len(requests) == 3  # chemical cached; detail retried


@pytest.mark.parametrize("detail", [["not", "an", "object"], "not json", 5])
def test_malformed_detail_is_a_transient_failure(detail: object) -> None:
    lookup, requests = _lookup(detail=detail)
    assert lookup.get_molecular_weight(CAS) is None
    lookup.get_molecular_weight(CAS)
    assert len(requests) == 3


def test_detail_server_error_is_not_cached_but_404_is() -> None:
    failing, failing_requests = _lookup(detail={"x": 1}, detail_status=500)
    assert failing.get_molecular_weight(CAS) is None
    failing.get_molecular_weight(CAS)
    assert len(failing_requests) == 3
    missing, missing_requests = _lookup(detail={"x": 1}, detail_status=404)
    assert missing.get_molecular_weight(CAS) is None
    missing.get_molecular_weight(CAS)
    assert len(missing_requests) == 2


def test_cas_search_sent_once_for_weight_properties_and_toxicity() -> None:
    lookup, requests = _lookup([_entry("Density", experimental=1.0)], [_rec("RfD")])
    lookup.get_molecular_weight(CAS)
    lookup.get_properties(CAS)
    lookup.get_toxicity_values(CAS)
    assert len(_chem_requests(requests)) == 1
    assert [r.url.path for r in requests] == [
        f"/api/c/{CAS}",
        f"/api/d/{DTX}",
        f"/api/p/{DTX}",
        f"/api/t/{DTX}",
    ]


# --- toxicity -------------------------------------------------------------------------------


def test_toxicity_values_found_with_units_and_source() -> None:
    records = [
        _rec("RfD", 0.5, "mg/kg-day", "SRC_A", "oral"),
        _rec("RfC", 0.25, "mg/m3", "SRC_A", "inhalation"),
        _rec("cancer slope factor", 3.0, "(mg/kg-day)-1", "SRC_B", "oral"),
        _rec("cancer unit risk", 0.001, "(mg/m3)-1", "SRC_B", "inhalation"),
    ]
    lookup, requests = _lookup(tox=records)
    none: dict[str, object] = {"endpoint": None, "assessment": None}
    assert lookup.get_toxicity_values(CAS) == {
        "rfd": {"value": 0.5, "unit": "mg/kg-day", "source": "SRC_A", "route": "oral", **none},
        "rfc": {"value": 0.25, "unit": "mg/m3", "source": "SRC_A", "route": "inhalation", **none},
        "sf": {"value": 3.0, "unit": "(mg/kg-day)-1", "source": "SRC_B", "route": "oral", **none},
        "iur": {
            "value": 0.001,
            "unit": "(mg/m3)-1",
            "source": "SRC_B",
            "route": "inhalation",
            **none,
        },
    }
    assert requests[1].url.path == f"/api/t/{DTX}"
    assert all(r.headers["x-test-key"] == "test-key" for r in requests)


def test_old_and_unconfigured_labels_are_ignored() -> None:
    records = [_rec(t, 1.0) for t in ("SF", "OSF", "IUR", "NOAEL", "LOAEL", "RfD (provisional)")]
    lookup, _ = _lookup(tox=records)
    assert lookup.get_toxicity_values(CAS) == {}


def test_extra_configured_toxicity_value_is_picked_up() -> None:
    spec = ToxicityValueSpec("mrl", ("MRL",), ("oral",), "lowest", "u")
    lookup, _ = _lookup(tox=[_rec("MRL", 4.0)], settings=_settings(tox_extra=(spec,)))
    assert set(lookup.get_toxicity_values(CAS)) == {"mrl"}


def test_alternate_labels_are_accepted() -> None:
    spec = ToxicityValueSpec("sf2", ("alpha", "beta"), ("oral",), "lowest", "u")
    records = [_rec("beta", 2.0)]
    lookup, _ = _lookup(tox=records, settings=_settings(tox_extra=(spec,)))
    assert lookup.get_toxicity_values(CAS)["sf2"]["value"] == 2.0


def test_wrong_route_is_ignored() -> None:
    records = [
        _rec("cancer slope factor", 9.0, route="inhalation"),
        _rec("cancer slope factor", 8.0, route="dermal"),
        _rec("cancer unit risk", 7.0, route="oral"),
        _rec("RfD", 6.0, route="inhalation"),
        _rec("RfC", 5.0, route="oral"),
    ]
    lookup, _ = _lookup(tox=records)
    assert lookup.get_toxicity_values(CAS) == {}


def test_route_comparison_is_case_insensitive() -> None:
    lookup, _ = _lookup(tox=[_rec("RfC", 1.0, route=" Inhalation ")])
    assert "rfc" in lookup.get_toxicity_values(CAS)


def test_route_not_specified_only_for_reference_values() -> None:
    records = [
        _rec("RfC", 1.0, route="not specified"),
        _rec("RfD", 2.0, route="not specified"),
        _rec("cancer slope factor", 3.0, route="not specified"),
        _rec("cancer unit risk", 4.0, route="not specified"),
    ]
    lookup, _ = _lookup(tox=records)
    assert set(lookup.get_toxicity_values(CAS)) == {"rfc", "rfd"}


@pytest.mark.parametrize("route", [None, 5, ["oral"]])
def test_record_without_text_route_is_ignored(route: object) -> None:
    lookup, _ = _lookup(tox=[_rec("RfD", 1.0, route=route)])
    assert lookup.get_toxicity_values(CAS) == {}


@pytest.mark.parametrize(
    "record",
    [
        _rec("RfD", None),
        _rec("RfD", "0.5"),
        _rec("RfD", True),
        _rec("RfD", math.nan),
        _rec("RfD", math.inf),
        _rec("RfD", 1.0, unit=None),
        _rec("RfD", 1.0, unit=" "),
    ],
)
def test_untrusted_toxicity_values_are_skipped(record: dict[str, object]) -> None:
    lookup, _ = _lookup(tox=_raw([record]))
    assert lookup.get_toxicity_values(CAS) == {}


def test_zero_toxicity_is_a_passthrough_value() -> None:
    lookup, _ = _lookup(tox=[_rec("RfD", 0.0)])
    assert lookup.get_toxicity_values(CAS)["rfd"]["value"] == 0.0


def test_record_for_another_chemical_is_ignored() -> None:
    records = [_rec("RfD", 1.0, dtxsid="DTXSID_OTHER"), _rec("RfC", 2.0, route="inhalation")]
    lookup, _ = _lookup(tox=records)
    assert set(lookup.get_toxicity_values(CAS)) == {"rfc"}


def test_record_without_dtxsid_is_ignored() -> None:
    record = _rec("RfD", 1.0)
    del record["dtxsid"]
    lookup, _ = _lookup(tox=[record])
    assert lookup.get_toxicity_values(CAS) == {}


def test_most_conservative_value_within_source() -> None:
    records = [
        _rec("cancer slope factor", 0.015, source="SRC_A"),
        _rec("cancer slope factor", 0.055, source="SRC_A"),
        _rec("cancer slope factor", 0.055, source="SRC_A"),  # identical duplicate
        _rec("RfC", 0.03, source="SRC_A", route="inhalation"),
        _rec("RfC", 0.01, source="SRC_A", route="inhalation"),
        _rec("cancer unit risk", 2.2, source="SRC_A", route="inhalation"),
        _rec("cancer unit risk", 7.8, source="SRC_A", route="inhalation"),
    ]
    lookup, _ = _lookup(tox=records)
    result = lookup.get_toxicity_values(CAS)
    assert result["sf"]["value"] == 0.055
    assert result["rfc"]["value"] == 0.01
    assert result["iur"]["value"] == 7.8


def test_source_priority_beats_conservatism() -> None:
    records = [
        _rec("RfD", 0.001, source="UNLISTED"),
        _rec("RfD", 0.9, source="SRC_B"),
        _rec("RfD", 0.5, source="SRC_A"),
        _rec("RfD", 0.7, source="SRC_A"),
    ]
    lookup, _ = _lookup(tox=records)
    chosen = lookup.get_toxicity_values(CAS)["rfd"]
    assert (chosen["value"], chosen["unit"], chosen["source"]) == (0.5, "u", "SRC_A")


def test_listed_source_beats_unlisted_one() -> None:
    records = [_rec("RfD", 0.001, source="UNLISTED"), _rec("RfD", 0.9, source="SRC_B")]
    lookup, _ = _lookup(tox=records)
    assert lookup.get_toxicity_values(CAS)["rfd"]["source"] == "SRC_B"


def test_only_unlisted_sources_use_the_first_one_seen() -> None:
    records = [
        _rec("RfD", 5.0, source="U1"),
        _rec("RfD", 3.0, source="U1"),
        _rec("RfD", 0.1, source="U2"),
    ]
    lookup, _ = _lookup(tox=records)
    chosen = lookup.get_toxicity_values(CAS)["rfd"]
    assert (chosen["value"], chosen["unit"], chosen["source"]) == (3.0, "u", "U1")


def test_record_without_source_name_still_qualifies() -> None:
    lookup, _ = _lookup(tox=[_rec("RfD", 1.0, source=None)])
    assert lookup.get_toxicity_values(CAS)["rfd"]["source"] == ""


@pytest.mark.parametrize("payload", [{"not": "a list"}, "not json", 3])
def test_malformed_toxval_response_gives_nothing(payload: object) -> None:
    lookup, requests = _lookup(tox=payload)
    assert lookup.get_toxicity_values(CAS) == {}
    count = len(requests)
    lookup.get_toxicity_values(CAS)
    assert len(requests) > count  # transient failure: retried, not cached


# --- caching, failures, isolation -----------------------------------------------------------


def test_success_is_cached_and_returned_as_copies() -> None:
    lookup, requests = _lookup([_entry("Density", experimental=1.0)], [_rec("RfD", 1.0)])
    first = lookup.get_properties(CAS)
    first["density"]["value"] = 99.0
    first.clear()
    assert lookup.get_properties(CAS)["density"]["value"] == 1.0
    tox = lookup.get_toxicity_values(CAS)
    tox["rfd"]["unit"] = "changed"
    tox.clear()
    assert lookup.get_toxicity_values(CAS)["rfd"]["unit"] == "u"
    assert len(requests) == 3  # chemical once, summary once, ToxVal once


def test_network_error_not_cached() -> None:
    lookup, requests = _lookup(fail=httpx.ConnectError("down"))
    assert lookup.get_properties(CAS) == {}
    assert lookup.get_toxicity_values(CAS) == {}
    assert lookup.get_molecular_weight(CAS) is None
    assert len(requests) == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chem_status": 500},
        {"summary_status": 500},
        {"summary": "not json"},
        {"summary": {"not": "a list"}},
    ],
)
def test_failures_return_empty_and_are_not_cached(kwargs: dict[str, object]) -> None:
    args: dict[str, object] = {"summary": [], **kwargs}
    lookup, requests = _lookup(**args)  # pyright: ignore[reportArgumentType]
    assert lookup.get_properties(CAS) == {}
    count = len(requests)
    lookup.get_properties(CAS)
    assert len(requests) > count


def test_toxval_failure_does_not_poison_properties() -> None:
    lookup, _ = _lookup([_entry("Density", experimental=1.0)], tox_status=500)
    assert lookup.get_toxicity_values(CAS) == {}
    assert "density" in lookup.get_properties(CAS)


# --- toxicity context: route, endpoint, assessment -----------------------------------------


def test_record_context_is_returned() -> None:
    records = [
        _rec("RfD", 0.5, route="oral", effect="reduced lymphocyte count", assessment="Non-cancer"),
        _rec("cancer slope factor", 3.0, effect="leukemia", assessment="Cancer"),
        _rec(
            "RfC",
            1.0,
            route="Inhalation",
            effect="neurological effects",
            assessment="Non-cancer",
        ),
    ]
    lookup, _ = _lookup(tox=records)
    result = lookup.get_toxicity_values(CAS)
    assert (result["rfd"]["route"], result["rfd"]["endpoint"], result["rfd"]["assessment"]) == (
        "oral",
        "reduced lymphocyte count",
        "non-cancer",
    )
    assert (result["sf"]["endpoint"], result["sf"]["assessment"]) == ("leukemia", "cancer")
    assert result["rfc"]["route"] == "inhalation"


@pytest.mark.parametrize("stated", ["-", "", "   ", None, 5, ["leukemia"]])
def test_unstated_or_untrusted_endpoint_is_none(stated: object) -> None:
    lookup, _ = _lookup(tox=[_rec("RfD", 1.0, effect=stated, assessment=stated)])
    chosen = lookup.get_toxicity_values(CAS)["rfd"]
    assert chosen["endpoint"] is None
    assert chosen["assessment"] is None


def test_route_reported_as_recorded_for_unspecified_route() -> None:
    lookup, _ = _lookup(tox=[_rec("RfC", 1.0, route="not specified")])
    assert lookup.get_toxicity_values(CAS)["rfc"]["route"] == "not specified"


def test_context_comes_from_the_chosen_record() -> None:
    records = [
        _rec("cancer slope factor", 0.015, effect="low-dose tumours", source="SRC_A"),
        _rec("cancer slope factor", 0.055, effect="leukemia", source="SRC_A"),
        _rec("cancer slope factor", 0.5, effect="other", source="UNLISTED"),
    ]
    lookup, _ = _lookup(tox=records)
    chosen = lookup.get_toxicity_values(CAS)["sf"]
    assert (chosen["value"], chosen["endpoint"], chosen["source"]) == (0.055, "leukemia", "SRC_A")


def test_context_survives_caching_as_copies() -> None:
    lookup, _ = _lookup(tox=[_rec("RfD", 1.0, effect="leukemia", assessment="Cancer")])
    first = lookup.get_toxicity_values(CAS)
    first["rfd"]["endpoint"] = "changed"
    first["rfd"]["route"] = "changed"
    again = lookup.get_toxicity_values(CAS)["rfd"]
    assert (again["endpoint"], again["route"]) == ("leukemia", "oral")


# --- the key of the current request ---------------------------------------------------------


def test_the_request_key_is_sent_instead_of_the_environment_key() -> None:
    lookup, requests = _lookup(detail=_detail(78.5))
    with COMPTOX_KEY.provide(SecretStr("turn-comptox-key")):  # pragma: allowlist secret
        lookup.get_molecular_weight(CAS)
    assert {r.headers["x-test-key"] for r in requests} == {"turn-comptox-key"}


def test_a_request_key_alone_is_enough() -> None:
    lookup, requests = _lookup(detail=_detail(78.5), env={})
    with COMPTOX_KEY.provide(SecretStr("turn-comptox-key")):  # pragma: allowlist secret
        assert lookup.get_molecular_weight(CAS) == 78.5
    assert requests


def test_the_environment_key_is_the_fallback_without_a_request_key() -> None:
    lookup, requests = _lookup(detail=_detail(78.5))
    lookup.get_molecular_weight(CAS)
    assert {r.headers["x-test-key"] for r in requests} == {"test-key"}


def test_the_key_of_one_request_is_not_kept_for_the_next() -> None:
    lookup, requests = _lookup(detail=_detail(78.5), env={})
    with COMPTOX_KEY.provide(SecretStr("first-turn-key")):  # pragma: allowlist secret
        lookup.get_molecular_weight(CAS)
    sent = len(requests)
    with pytest.raises(RuntimeError, match="TEST_KEY_VAR"):
        lookup.get_properties(CAS)
    assert len(requests) == sent


def test_certificates_are_fully_verified_unless_only_their_dates_are_waived() -> None:
    import ssl
    from dataclasses import replace

    assert tls_verification(_settings()) is True
    context = tls_verification(replace(_settings(), accept_expired_certificate=True))
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname and context.verify_mode is ssl.CERT_REQUIRED
    assert context.verify_flags & 0x200000  # dates skipped, nothing else
