"""The payload models stay in step with the tool result types, and refuse untrusted shapes."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from api.services.projectors.payloads import (
    ActivityCasePayload,
    AssessedPayload,
    BoundPayload,
    DrivingActivityPayload,
    EmissionPayload,
    ExposurePayload,
    IndustryPayload,
    MeteorologyPayload,
    MonitoringPayload,
    NeiPayload,
    OccupationalPayload,
    PopulationPayload,
    PropertiesPayload,
    RangeEntryPayload,
    ReadAcrossPayload,
    SccMatchPayload,
    ScenarioFactorPayload,
    ScenarioReceptorPayload,
    ScenarioRoutePayload,
    ScreenedOutPayload,
    StackExposurePayload,
    StackPayload,
    StageRoutePayload,
    WorkerActivityPayload,
    WorkerCasePayload,
    WorstCaseScenarioPayload,
    decode_json,
    validate,
)
from tests.api.services.projectors.factories import record
from tools.schemas import (
    ActivityCase,
    ChemicalProperties,
    DrivingActivity,
    EmissionRecord,
    ExposureRange,
    FacilityAssessment,
    FacilityExposure,
    FacilityIndustry,
    Meteorology,
    MonitoringSummary,
    NeiStackResult,
    OccupationalExposure,
    Population,
    RangeEntry,
    ReadAcrossMatch,
    SccMatch,
    ScenarioFactor,
    ScenarioReceptor,
    ScenarioRoute,
    ScreenedOut,
    ScreeningBound,
    StackExposure,
    StackParameters,
    StageRoute,
    WorkerActivity,
    WorkerCase,
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
    (OccupationalPayload, OccupationalExposure),
    (WorkerCasePayload, WorkerCase),
    (ActivityCasePayload, ActivityCase),
    (WorkerActivityPayload, WorkerActivity),
    (DrivingActivityPayload, DrivingActivity),
    (StageRoutePayload, StageRoute),
    (ScenarioRoutePayload, ScenarioRoute),
    (MonitoringPayload, MonitoringSummary),
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


def _case_payload(tier: object) -> dict[str, object]:
    return {
        "setting": "indoor",
        "estimator": "two_zone",
        "airflow_m3_per_s": 1.0,
        "room_m3": 50.0,
        "air_exchange_per_h": 4.0,
        "generation_g_per_s": 0.5,
        "capped": False,
        "risk_tier": tier,
    }


@pytest.mark.parametrize("old", ["exceedance", "elevated", "acceptable", "above", 3])
def test_an_unknown_band_reads_as_not_reported_and_keeps_the_rest(old: object) -> None:
    parsed = validate(WorkerCasePayload, {**_case_payload(old), "twa_mg_m3": 2.0})
    assert parsed is not None
    assert parsed.risk_tier is None
    assert parsed.twa_mg_m3 == 2.0


@pytest.mark.parametrize("band", ["high", "moderate", "low"])
def test_a_known_band_is_kept(band: str) -> None:
    parsed = validate(WorkerCasePayload, _case_payload(band))
    assert parsed is not None and parsed.risk_tier == band


def test_a_case_keeps_every_field_the_tool_reported() -> None:
    parsed = validate(WorkerCasePayload, _case_payload("low"))
    assert parsed is not None
    assert (parsed.setting, parsed.estimator, parsed.room_m3) == ("indoor", "two_zone", 50.0)
    assert (parsed.air_exchange_per_h, parsed.generation_g_per_s) == (4.0, 0.5)
    assert parsed.capped is False


def test_a_case_with_nothing_computed_is_all_absent() -> None:
    parsed = validate(WorkerCasePayload, {})
    assert parsed is not None
    assert not any(v is not None for v in parsed.model_dump().values())


@pytest.mark.parametrize(
    "change",
    [
        {"capped": "yes"},
        {"room_m3": True},
        {"generation_g_per_s": float("nan")},
        {"estimator": "guess"},
    ],
)
def test_untrusted_worker_case_values_are_refused(change: dict[str, object]) -> None:
    assert validate(WorkerCasePayload, {**_case_payload("low"), **change}) is None


def test_an_activity_case_needs_its_average_and_a_known_estimator() -> None:
    case = {"estimator": "mass_balance", "capped": True, "twa_mg_m3": 1.0}
    assert validate(ActivityCasePayload, case) is not None
    assert validate(ActivityCasePayload, {"estimator": "mass_balance", "capped": True}) is None
