"""Tests for the TSCA conditions-of-use mapping (synthetic crosswalks, one real-file check)."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest

from config.conditions_of_use import ConditionsSettings, get_conditions_settings
from tools.emissions.helpers.inventory import conditions as module
from tools.emissions.helpers.inventory.conditions import (
    ConditionsMapper,
    Crosswalk,
    get_crosswalk,
    load_crosswalk,
)

HEADER = (
    "mapping_level,tri_form_r_section,tri_subuse_code,tsca_lifecycle_stage,"
    "tsca_cou_category,mapping_strength,tri_activity_category"
)
ROWS = [
    "1_lifecycle_stage,Part II Section 3.2a,,Processing,Cat reactant,Direct,As a reactant",
    "1_lifecycle_stage,Part II Section 3.1a,,Manufacturing,Cat produce,Direct,Produce",
    "1_lifecycle_stage,Part II Section 3.3c,,Industrial use,Cat ancillary,Direct (group),Ancillary",
    "1_lifecycle_stage,Part II Section 3.3c,,Commercial use,Cat product,Partial,Ancillary",
    "1_lifecycle_stage,Part II Section 3.2e,,Processing,Not a COU,None (CDR exempt),Impurity",
    "1_lifecycle_stage,Part II Section 3.3 (a; b; c),,Industrial use,Parent,Direct,Parent",
    "2_cdr_function_code,Part II Section 3.2a,,Processing,Function row,Inferred,As a reactant",
    "1_lifecycle_stage,Part II Section 3.2a,P101,Processing,Sub-use row,Inferred,As a reactant",
    "1_lifecycle_stage,Part II Section 3.2a,,Processing,Cat reactant,Direct,As a reactant",
    "1_lifecycle_stage,Part II Section 3.2b,,,No stage,Direct,Formulation",
]


def _settings(tmp_path: Path, text: str | None = None) -> ConditionsSettings:
    path = tmp_path / "x.csv"
    path.write_text(text if text is not None else "\n".join([HEADER, *ROWS]) + "\n", "utf-8")
    return dataclasses.replace(get_conditions_settings(), crosswalk_path=path)


def _mapper(tmp_path: Path, text: str | None = None) -> ConditionsMapper:
    settings = _settings(tmp_path, text)
    return ConditionsMapper(load_crosswalk(settings), settings)


def _cats(result: module.Conditions) -> list[str]:
    return [c["cou_category"] for c in result.conditions_of_use]


def test_one_activity_one_condition(tmp_path: Path) -> None:
    result = _mapper(tmp_path)(frozenset({"3.2a"}), True)
    assert result.conditions_of_use == [
        {
            "tri_activity": "As a reactant",
            "tri_section": "3.2a",
            "lifecycle_stage": "Processing",
            "cou_category": "Cat reactant",
            "mapping_strength": "Direct",
        },
    ]
    assert result.lifecycle_stages == ["Processing"] and result.note is None


def test_one_activity_can_give_two_conditions(tmp_path: Path) -> None:
    result = _mapper(tmp_path)(frozenset({"3.3c"}), True)
    assert _cats(result) == ["Cat ancillary", "Cat product"]
    assert result.lifecycle_stages == ["Industrial use", "Commercial use"]


def test_several_activities_are_ordered_by_section_with_stages_once(tmp_path: Path) -> None:
    result = _mapper(tmp_path)(frozenset({"3.3c", "3.1a", "3.2a"}), True)
    assert _cats(result) == ["Cat produce", "Cat reactant", "Cat ancillary", "Cat product"]
    assert result.lifecycle_stages == [
        "Manufacturing",
        "Processing",
        "Industrial use",
        "Commercial use",
    ]


def test_finer_and_unusable_rows_are_ignored(tmp_path: Path) -> None:
    result = _mapper(tmp_path)(frozenset({"3.2a"}), True)
    assert _cats(result) == ["Cat reactant"]  # no function row, no sub-use row, no duplicate


def test_impurity_keeps_its_cdr_exempt_strength(tmp_path: Path) -> None:
    only = _mapper(tmp_path)(frozenset({"3.2e"}), True).conditions_of_use[0]
    assert only["cou_category"] == "Not a COU"
    assert only["mapping_strength"] == "None (CDR exempt)"


def test_unmapped_activity_is_dropped_and_warned_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mapper = _mapper(tmp_path)
    with caplog.at_level(logging.WARNING):
        both = mapper(frozenset({"3.2a", "3.1d"}), True)
        mapper(frozenset({"3.1d"}), True)
    assert _cats(both) == ["Cat reactant"]
    assert len([r for r in caplog.records if "Section 3.1d" in r.getMessage()]) == 1


def test_only_unmapped_activities(tmp_path: Path) -> None:
    result = _mapper(tmp_path)(frozenset({"3.1d"}), True)
    assert result.conditions_of_use == [] and result.note == module.NO_ROWS


def test_row_without_a_stage_is_ignored(tmp_path: Path) -> None:
    assert _mapper(tmp_path)(frozenset({"3.2b"}), True).note == module.NO_ROWS


def test_no_activity_reported(tmp_path: Path) -> None:
    result = _mapper(tmp_path)(frozenset(), True)
    assert (result.conditions_of_use, result.lifecycle_stages) == ([], [])
    assert result.note == module.NO_ACTIVITY


def test_activity_data_not_returned(tmp_path: Path) -> None:
    assert _mapper(tmp_path)(frozenset(), False).note == module.NO_ACTIVITY_DATA


def test_results_are_independent_copies(tmp_path: Path) -> None:
    mapper = _mapper(tmp_path)
    first = mapper(frozenset({"3.2a"}), True)
    first.conditions_of_use[0]["cou_category"] = "changed"
    first.lifecycle_stages.append("x")
    again = mapper(frozenset({"3.2a"}), True)
    assert _cats(again) == ["Cat reactant"] and again.lifecycle_stages == ["Processing"]


def test_missing_file_makes_conditions_unavailable_with_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = dataclasses.replace(get_conditions_settings(), crosswalk_path=tmp_path / "none.csv")
    get_crosswalk.cache_clear()
    with caplog.at_level(logging.WARNING):
        mapper = ConditionsMapper(get_crosswalk(settings), settings)
        get_crosswalk(settings)
    result = mapper(frozenset({"3.2a"}), True)
    assert result.conditions_of_use == [] and "none.csv" in str(result.note)
    assert len([r for r in caplog.records if "none.csv" in r.getMessage()]) == 1
    get_crosswalk.cache_clear()


def test_missing_column_makes_conditions_unavailable(tmp_path: Path) -> None:
    text = HEADER.replace("tsca_cou_category,", "") + "\n"
    note = _mapper(tmp_path, text)(frozenset({"3.2a"}), True).note
    assert note is not None and "missing column tsca_cou_category" in note


def test_the_crosswalk_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    get_crosswalk.cache_clear()
    settings = _settings(tmp_path)
    reads: list[int] = []
    real = module.load_crosswalk

    def counting(s: ConditionsSettings) -> Crosswalk:
        reads.append(1)
        return real(s)

    monkeypatch.setattr(module, "load_crosswalk", counting)
    for _ in range(5):
        get_crosswalk(settings)
    assert len(reads) == 1
    get_crosswalk.cache_clear()


def test_the_real_crosswalk_covers_every_configured_flag() -> None:
    settings = get_conditions_settings()
    crosswalk = load_crosswalk(settings)
    assert crosswalk.unavailable is None
    for column, section in settings.flags:
        assert crosswalk.by_section.get(section), f"{column} ({section}) has no crosswalk row"
    ancillary = {c["lifecycle_stage"] for c in crosswalk.by_section["3.3c"]}
    assert ancillary == {"Industrial use", "Commercial use"}
    assert crosswalk.by_section["3.2e"][0]["mapping_strength"] == "None (CDR exempt)"
    assert "3.3 (a, b, c)" not in crosswalk.by_section
