"""The payload models stay in step with the tool result types, and refuse untrusted shapes."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from api.services.projectors.payloads import (
    AssessedPayload,
    BoundPayload,
    EmissionPayload,
    ExposurePayload,
    IndustryPayload,
    MeteorologyPayload,
    NeiPayload,
    PopulationPayload,
    PropertiesPayload,
    RangeEntryPayload,
    ReadAcrossPayload,
    SccMatchPayload,
    ScenarioFactorPayload,
    ScenarioReceptorPayload,
    ScreenedOutPayload,
    StackExposurePayload,
    StackPayload,
    WorstCaseScenarioPayload,
    decode_json,
    validate,
)
from tests.api.services.projectors.factories import record
from tools.schemas import (
    ChemicalProperties,
    EmissionRecord,
    ExposureRange,
    FacilityAssessment,
    FacilityExposure,
    FacilityIndustry,
    Meteorology,
    NeiStackResult,
    Population,
    RangeEntry,
    ReadAcrossMatch,
    SccMatch,
    ScenarioFactor,
    ScenarioReceptor,
    ScreenedOut,
    ScreeningBound,
    StackExposure,
    StackParameters,
    WorstCaseScenario,
)

PAIRS: list[tuple[type[BaseModel], type]] = [
    (EmissionPayload, EmissionRecord),
    (IndustryPayload, FacilityIndustry),
    (StackPayload, StackParameters),
    (NeiPayload, NeiStackResult),
    (SccMatchPayload, SccMatch),
    (PropertiesPayload, ChemicalProperties),
    (ReadAcrossPayload, ReadAcrossMatch),
    (MeteorologyPayload, Meteorology),
    (PopulationPayload, Population),
    (StackExposurePayload, StackExposure),
    (RangeEntryPayload, RangeEntry),
    (ExposurePayload, FacilityExposure),
    (AssessedPayload, FacilityAssessment),
    (ScreenedOutPayload, ScreenedOut),
    (BoundPayload, ScreeningBound),
    (WorstCaseScenarioPayload, WorstCaseScenario),
    (ScenarioFactorPayload, ScenarioFactor),
    (ScenarioReceptorPayload, ScenarioReceptor),
]


@pytest.mark.parametrize(("model", "result_type"), PAIRS, ids=lambda p: getattr(p, "__name__", ""))
def test_every_field_read_still_exists_in_the_tool_result(
    model: type[BaseModel],
    result_type: type,
) -> None:
    unknown = set(model.model_fields) - set(result_type.__annotations__)
    assert not unknown


def test_the_exposure_range_fields_exist_in_the_tool_result() -> None:
    from api.services.projectors.payloads import ExposureRangePayload

    unknown = set(ExposureRangePayload.model_fields) - set(ExposureRange.__annotations__)
    assert not unknown


def test_a_valid_record_is_accepted() -> None:
    assert validate(EmissionPayload, record()) is not None


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": 123.0},
        {"longitude": -181.0},
        {"emission_rate": True},
        {"emission_rate": "1.0"},
        {"emission_rate": float("nan")},
        {"total_release": float("inf")},
        {"reporting_year": 2020.0},
    ],
)
def test_untrusted_values_are_refused(change: dict[str, object]) -> None:
    assert validate(EmissionPayload, {**record(), **change}) is None


def test_decode_json_only_accepts_json_text() -> None:
    assert decode_json('{"a": 1}') == {"a": 1}
    assert decode_json("not json") is None
    assert decode_json(["a list of blocks"]) is None


def test_a_json_nan_literal_is_refused_as_a_number() -> None:
    value = decode_json('{"wind_speed": NaN}')
    assert validate(MeteorologyPayload, value) is None
