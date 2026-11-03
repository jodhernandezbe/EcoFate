"""Tests for CID discovery, the record fetch and resolve_compound_data (no network)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from config.pubchem import PubchemSettings, get_pubchem_settings
from tests.tools.informatics.helpers.pubchem.fakes import FakeJson
from tests.tools.informatics.helpers.pubchem.records import Json, info, record
from tools.http import HttpRequestError
from tools.informatics.helpers.pubchem.client import (
    SearchType,
    fetch_pubchem_pug_view_json,
    get_cid_by_identifier,
)
from tools.informatics.helpers.pubchem.resolve import resolve_compound_data

SETTINGS: PubchemSettings = get_pubchem_settings()
BUTANE_CAS = "106-97-8"
BUTANE_CID = 7843


def _ids(*cids: object) -> Json:
    return {"IdentifierList": {"CID": list(cids)}}


def _name(query: str) -> str:
    return SETTINGS.name_url(query)


def _cid(query: str, kind: str, answers: Mapping[str, object]) -> tuple[int | None, str | None]:
    result = get_cid_by_identifier(
        query,
        cast(SearchType, kind),
        client=FakeJson(answers),
        settings=SETTINGS,
    )
    return result.value, result.reason


def test_cid_for_a_smiles_uses_the_canonical_smiles_endpoint() -> None:
    url = SETTINGS.smiles_url("CCCC")
    fake = FakeJson({url: _ids(BUTANE_CID)})
    found = get_cid_by_identifier("C(C)CC", client=fake, settings=SETTINGS)
    assert found.value == BUTANE_CID and found.reason is None
    assert fake.calls == [url]


def test_cid_for_a_cas_number_uses_the_name_endpoint() -> None:
    assert _cid(BUTANE_CAS, "cas", {_name(BUTANE_CAS): _ids(BUTANE_CID)}) == (BUTANE_CID, None)


def test_cid_for_hexane_cas_number() -> None:
    assert _cid("110-54-3", "cas", {_name("110-54-3"): _ids(8058)})[0] == 8058


def test_cid_for_a_name() -> None:
    assert _cid("butane", "name", {_name("butane"): _ids(BUTANE_CID)})[0] == BUTANE_CID


def test_not_found_has_a_reason() -> None:
    value, reason = _cid("nothing", "name", {})
    assert value is None and reason is not None and "no compound" in reason


def test_several_cids_are_ambiguous_and_none_is_picked() -> None:
    value, reason = _cid("x", "name", {_name("x"): _ids(1, 2)})
    assert value is None and reason is not None and "ambiguous" in reason


def test_repeated_same_cid_is_one_compound() -> None:
    assert _cid("x", "name", {_name("x"): _ids(5, 5)})[0] == 5


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        None,
        {"IdentifierList": []},
        {"IdentifierList": {"CID": "7843"}},
        _ids(),
        _ids(0),
        _ids(-3),
        _ids(True),
        _ids("7843"),
        _ids(1.5),
        _ids(7843, None),
    ],
)
def test_malformed_answer_gives_no_cid(payload: object) -> None:
    value, reason = _cid("x", "name", {_name("x"): payload})
    assert value is None and reason is not None and "not understood" in reason


def test_unreachable_service_gives_a_reason_and_does_not_raise() -> None:
    answers = {_name("x"): HttpRequestError("request failed after 3 attempts: HTTP 503", 503)}
    value, reason = _cid("x", "name", answers)
    assert value is None and reason is not None and "could not be reached" in reason


def test_malformed_smiles_raises_without_a_request() -> None:
    fake = FakeJson({})
    with pytest.raises(ValueError, match="could not parse"):
        get_cid_by_identifier("C(C", client=fake, settings=SETTINGS)
    assert fake.calls == []


def test_unknown_search_type_raises() -> None:
    with pytest.raises(ValueError, match="search type"):
        _cid("x", "inchi", {})


def test_fetch_returns_the_record_unchanged() -> None:
    body = record(cas=[BUTANE_CAS])
    url = SETTINGS.record_url(BUTANE_CID)
    found = fetch_pubchem_pug_view_json(BUTANE_CID, client=FakeJson({url: body}), settings=SETTINGS)
    assert found.value == body


@pytest.mark.parametrize("payload", [{}, [], "x", None, {"Record": []}, {"Fault": {}}])
def test_fetch_without_a_record_gives_a_reason(payload: object) -> None:
    url = SETTINGS.record_url(5)
    result = fetch_pubchem_pug_view_json(5, client=FakeJson({url: payload}), settings=SETTINGS)
    assert result.value is None and result.reason is not None and "not understood" in result.reason


def test_fetch_404_gives_a_reason() -> None:
    result = fetch_pubchem_pug_view_json(5, client=FakeJson({}), settings=SETTINGS)
    assert result.value is None and result.reason is not None and "no compound" in result.reason


@pytest.mark.parametrize("cid", [0, -1, True])
def test_fetch_with_an_invalid_cid_raises_without_a_request(cid: int) -> None:
    fake = FakeJson({})
    with pytest.raises(ValueError, match="positive integer"):
        fetch_pubchem_pug_view_json(cid, client=fake, settings=SETTINGS)
    assert fake.calls == []


def _world(cas_in_record: list[str], cid_body: object | None = None) -> FakeJson:
    return FakeJson(
        {
            _name(BUTANE_CAS): cid_body if cid_body is not None else _ids(BUTANE_CID),
            SETTINGS.smiles_url("CCCC"): _ids(BUTANE_CID),
            _name("butane"): _ids(BUTANE_CID),
            SETTINGS.record_url(BUTANE_CID): record(cas=cas_in_record),
        },
    )


def test_cas_number_resolves_when_the_record_confirms_it() -> None:
    found = resolve_compound_data(BUTANE_CAS, client=_world([BUTANE_CAS]), settings=SETTINGS)
    assert (found.kind, found.cid, found.warnings) == ("cas", BUTANE_CID, ())
    assert found.record is not None


def test_record_listing_another_cas_number_is_rejected() -> None:
    found = resolve_compound_data(BUTANE_CAS, client=_world(["71-43-2"]), settings=SETTINGS)
    assert found.cid == BUTANE_CID and found.record is None
    assert "not confirmed" in found.warnings[0]


def test_record_without_cas_numbers_is_rejected() -> None:
    found = resolve_compound_data(BUTANE_CAS, client=_world([]), settings=SETTINGS)
    assert found.record is None and "not confirmed" in found.warnings[0]


def test_smiles_and_name_need_no_cas_confirmation() -> None:
    world = _world([])
    smiles = resolve_compound_data("CCCC", client=world, settings=SETTINGS)
    named = resolve_compound_data("butane", client=world, settings=SETTINGS)
    assert (smiles.kind, named.kind) == ("smiles", "name")
    assert smiles.record is not None and named.record is not None


def test_ambiguous_identifier_stops_the_chain() -> None:
    fake = _world([BUTANE_CAS], cid_body=_ids(1, 2))
    found = resolve_compound_data(BUTANE_CAS, client=fake, settings=SETTINGS)
    assert found.cid is None and found.record is None and "ambiguous" in found.warnings[0]
    assert SETTINGS.record_url(1) not in fake.calls


def test_missing_record_keeps_the_cid_and_says_why() -> None:
    fake = FakeJson({_name(BUTANE_CAS): _ids(BUTANE_CID)})
    found = resolve_compound_data(BUTANE_CAS, client=fake, settings=SETTINGS)
    assert found.cid == BUTANE_CID and found.record is None and found.warnings


def test_unknown_identifier_is_a_warning_not_an_error() -> None:
    found = resolve_compound_data("unobtainium", client=FakeJson({}), settings=SETTINGS)
    assert found.cid is None and "no compound" in found.warnings[0]


def test_malformed_stated_smiles_raises() -> None:
    with pytest.raises(ValueError, match="could not parse"):
        resolve_compound_data("C(C", client=FakeJson({}), settings=SETTINGS, kind="smiles")


def test_empty_identifier_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        resolve_compound_data(" ", client=FakeJson({}), settings=SETTINGS)


def test_info_helper_keeps_a_separate_unit() -> None:
    assert info("1", "g/mol")["Value"] == {"StringWithMarkup": [{"String": "1"}], "Unit": "g/mol"}
