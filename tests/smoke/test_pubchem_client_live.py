"""Live smoke test for the PubChem client and the fallback (real PubChem, no key needed).

Run with ``uv run pytest -m smoke``. Butane is the reference chemical: CAS 106-97-8, CID 7843.
The assertions are about shape and plausible ranges, not exact measurements, so a revised
PubChem value cannot break them, but a changed PUG View layout will.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from config.loader import get_unit_settings
from config.pubchem import CacheSettings, PubchemSettings, get_pubchem_settings
from tools.informatics.helpers.pubchem import PubchemLookup, build_client, resolve_compound_data

pytestmark = pytest.mark.smoke

BUTANE_CAS = "106-97-8"
BUTANE_CID = 7843


@pytest.fixture(scope="module")
def settings() -> PubchemSettings:
    shipped = get_pubchem_settings()
    return replace(shipped, cache=CacheSettings(False, shipped.cache.path, shipped.cache.ttl_days))


def test_cas_number_resolves_to_a_confirmed_butane_record(settings: PubchemSettings) -> None:
    compound = resolve_compound_data(BUTANE_CAS, client=build_client(settings), settings=settings)
    assert compound.kind == "cas" and compound.cid == BUTANE_CID
    assert compound.record is not None and compound.warnings == ()


def test_smiles_and_name_resolve_to_the_same_compound(settings: PubchemSettings) -> None:
    client = build_client(settings)
    assert resolve_compound_data("C(C)CC", client=client, settings=settings).cid == BUTANE_CID
    assert resolve_compound_data("butane", client=client, settings=settings).cid == BUTANE_CID


def _lookup(settings: PubchemSettings) -> PubchemLookup:
    return PubchemLookup(build_client(settings), settings, get_unit_settings().aliases)


def test_fallback_reads_butane_weight_and_pressure_and_refuses_its_density(
    settings: PubchemSettings,
) -> None:
    offered = _lookup(settings).candidates(
        BUTANE_CAS,
        ["molecular_weight", "vapor_pressure", "density"],
    )
    assert offered.problem is None
    assert offered.values["molecular_weight"].value == pytest.approx(58.12, abs=0.01)
    assert 1000 < offered.values["vapor_pressure"].value < 3000  # mmHg near room temperature
    # Butane's only density with a unit also states a pressure ("(p>1 atm)"): not a clear
    # statement, so the field stays empty with a reason instead of a guess.
    assert "density" not in offered.values and "density" in offered.reasons


def test_fallback_reads_hexane_density(settings: PubchemSettings) -> None:
    offered = _lookup(settings).candidates("110-54-3", ["density"])
    assert 0.6 < offered.values["density"].value < 0.7  # g/cm^3


def test_benzene_limits_are_read_from_the_live_record(settings: PubchemSettings) -> None:
    lookup = PubchemLookup(build_client(settings), settings, get_unit_settings().aliases)
    limits = lookup.limits("71-43-2", 78.11)
    assert limits["oel_source"] is not None and limits["oel_twa_mg_m3"] is not None
    assert 0.1 < limits["oel_twa_mg_m3"] < 50  # mg/m^3; a changed PUG View layout breaks this
    assert "niosh_idlh" in limits["limits"]
