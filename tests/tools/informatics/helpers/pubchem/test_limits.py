"""Tests for the occupational limits read from a PUG View record (synthetic values)."""

from __future__ import annotations

import pytest

from config.pubchem import get_pubchem_settings
from models.chemistry.air_units import ppm_to_mg_per_m3
from tests.tools.informatics.helpers.pubchem.records import Json, info, section
from tools.informatics.helpers.pubchem.limits import read_limits
from tools.schemas import OccupationalLimits

SETTINGS = get_pubchem_settings()
LIMITS = SETTINGS.limits
RATIO = SETTINGS.agreement_ratio
WEIGHT = 100.0  # g/mol, synthetic
V = LIMITS.molar_volume_l_per_mol


def named(name: str | None, text: str) -> Json:
    entry = info(text)
    if name is not None:
        entry["Name"] = name
    return entry


def control(**sections: list[Json]) -> Json:
    """A record whose "Exposure Control and Personal Protection" holds the given limits."""
    headings = {
        "pel": "Permissible Exposure Limit (PEL)",
        "rel": "Recommended Exposure Limit (REL)",
        "tlv": "Threshold Limit Values (TLV)",
        "idlh": "Immediately Dangerous to Life or Health (IDLH)",
        "pac": "Protective Action Criteria (PAC)",
    }
    children = [section(headings[k], entries=v) for k, v in sections.items()]
    body = section(
        "Safety and Hazards",
        section("Exposure Control and Personal Protection", *children),
    )
    return {"Record": {"Section": [body]}}


def _read(record: Json, weight: float | None = WEIGHT) -> OccupationalLimits:
    return read_limits(record, weight, LIMITS, RATIO)


def test_ppm_is_converted_with_the_molecular_weight() -> None:
    result = _read(control(pel=[named("PEL-TWA (8-Hour Time Weighted Average)", "50 ppm")]))
    assert result["oel_twa_mg_m3"] == pytest.approx(50 * WEIGHT / 24.45)
    assert result["limits"]["osha_pel"]["converted_from_ppm"] is True


def test_mg_per_cubic_meter_is_used_as_given() -> None:
    result = _read(control(pel=[named("PEL-TWA", "5 mg/cu m")]), weight=None)
    assert result["oel_twa_mg_m3"] == pytest.approx(5.0)
    assert result["limits"]["osha_pel"]["converted_from_ppm"] is False


def test_ppm_without_a_weight_is_refused_with_a_reason() -> None:
    result = _read(control(pel=[named("PEL-TWA", "50 ppm")]), weight=None)
    assert result["oel_twa_mg_m3"] is None
    assert "molecular weight is unknown" in result["reasons"]["osha_pel"]
    assert result["warnings"]


def test_osha_wins_then_niosh_then_acgih() -> None:
    record = control(
        pel=[named("PEL-TWA", "1 ppm")],
        rel=[named("REL-TWA (Time Weighted Average)", "2 ppm")],
        tlv=[named(None, "8 hr Time Weighted Avg (TWA): 3 ppm; 15 min STEL: 6 ppm")],
    )
    result = _read(record)
    assert result["oel_source"] == "OSHA PEL-TWA (PubChem)"
    assert result["oel_twa_mg_m3"] == pytest.approx(ppm_to_mg_per_m3(1, WEIGHT, V))


def test_falls_back_to_acgih_when_it_is_the_only_one() -> None:
    result = _read(control(tlv=[named(None, "0.5 ppm as TWA; 2.5 ppm as STEL; (skin)")]))
    assert result["oel_source"] == "ACGIH TLV-TWA (PubChem)"
    assert result["oel_twa_mg_m3"] == pytest.approx(ppm_to_mg_per_m3(0.5, WEIGHT, V))
    assert result["limits"]["acgih_tlv_stel"]["value"] == pytest.approx(
        ppm_to_mg_per_m3(2.5, WEIGHT, V),
    )


def test_no_twa_keeps_idlh_and_pac() -> None:
    record = control(
        idlh=[named(None, "500 ppm ; A potential occupational carcinogen. (NIOSH, 2024)")],
        pac=[named("PAC-1", "52 [ppm]"), named("PAC-2", "800 [ppm]"), named("PAC-3", "4000 [ppm]")],
    )
    result = _read(record)
    assert result["oel_twa_mg_m3"] is None and result["oel_source"] is None
    assert result["limits"]["niosh_idlh"]["value"] == pytest.approx(
        ppm_to_mg_per_m3(500, WEIGHT, V),
    )
    assert set(result["limits"]) == {"niosh_idlh", "pac_1", "pac_2", "pac_3"}
    assert result["warnings"]


@pytest.mark.parametrize("text", ["1-5 ppm", "> 5 ppm", "1 ppm 5 ppm", "see appendix", "0 ppm"])
def test_unclear_named_statements_are_skipped(text: str) -> None:
    result = _read(control(pel=[named("PEL-TWA", text)]))
    assert result["oel_twa_mg_m3"] is None
    assert "osha_pel" in result["reasons"] or text == "see appendix"


def test_unnamed_or_stel_entries_are_not_a_twa() -> None:
    record = control(
        pel=[named("PEL-STEL (Short Term Exposure Limit)", "5 ppm"), named(None, "1 ppm")],
    )
    assert _read(record)["oel_twa_mg_m3"] is None


def test_disagreeing_statements_give_no_value() -> None:
    record = control(pel=[named("PEL-TWA", "1 ppm"), named("PEL-TWA", "10 ppm")])
    result = _read(record)
    assert result["oel_twa_mg_m3"] is None
    assert "disagree" in result["reasons"]["osha_pel"]


def test_missing_section_gives_reasons_not_an_error() -> None:
    result = _read({"Record": {"Section": []}})
    assert result["limits"] == {} and result["oel_twa_mg_m3"] is None
    assert result["warnings"]


def test_untrusted_shapes_do_not_raise() -> None:
    assert _read({"Record": "x"})["limits"] == {}
    assert _read({})["limits"] == {}


def test_ppm_conversion_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        ppm_to_mg_per_m3(1.0, 0.0, 24.45)
    with pytest.raises(ValueError):
        ppm_to_mg_per_m3(float("nan"), 100.0, 24.45)
