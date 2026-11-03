"""Synthetic inputs and fake steps for the batch assessment tests (never real data)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from config.assessment import AssessmentSettings, ScreeningSettings
from tests.tools.emissions.records import emission_record
from tools.assessment.helpers.steps import Steps
from tools.schemas import (
    EmissionRecord,
    FacilityExposure,
    FacilityIndustry,
    Meteorology,
    NeiStackResult,
    Population,
    SccLookupResult,
    SccMatch,
    StackParameters,
    Toxicity,
)

SCREENING = ScreeningSettings(hq=0.1, cancer_risk=1e-6, ambient_temperatures_k=(250.0, 300.0))
SETTINGS = AssessmentSettings(
    max_facilities=3,
    max_refined=50,
    max_workers=2,
    scc_min_score=0.5,
    max_scc_stacks=2,
    inventory_cache_seconds=0,
    max_worst_case_listed=4,
    max_screened_out_listed=2,
    weather_cell_deg=0.25,
    screening=SCREENING,
)
TOXICITY = Toxicity(rfc=1.0, iur=None)


def record(frs_id: str = "F1", **over: object) -> EmissionRecord:
    base = emission_record(frs_id, 1.0)
    merged: EmissionRecord = {**base, **over}  # type: ignore[typeddict-item]
    return merged


def stack(height: float, source: str = "NEI", scc: str | None = None) -> StackParameters:
    return StackParameters(
        stack_height=height,
        stack_diameter=1.0,
        exit_velocity=2.0,
        exit_temperature=300.0,
        source=source,  # type: ignore[typeddict-item]
        scc=scc,
        warnings=[],
    )


def match(scc: str, score: float) -> SccMatch:
    return SccMatch(
        scc=scc,
        level_one="L1",
        level_two="L2",
        level_three="L3",
        level_four=f"Process {scc}",
        sector="Sector",
        score=score,
    )


GLOBAL = stack(3.0, "AirToxScreen global default")
WEATHER = Meteorology(
    wind_speed=3.0,
    wind_direction=180.0,
    stability_class="D",
    ambient_temperature=290.0,
    source="Synthetic weather",
    warnings=[],
)
PEOPLE = Population(
    total_population=100,
    age_distribution={"18-64": 100.0},
    source="Synthetic census",
    warnings=[],
)


def hq_of(rate: float, height: float, temperature: float) -> float:
    """The fake exposure's HQ: linear in the rate, lower stacks and hotter days give more."""
    return rate / height * temperature / 300.0


def _entry(values: list[float]) -> dict[str, float | int]:
    low, high = min(values), max(values)
    return {
        "low": low,
        "high": high,
        "low_stack": values.index(low) + 1,
        "high_stack": values.index(high) + 1,
    }


def _result(
    number: int,
    params: StackParameters,
    hq: float,
    risk: float | None,
) -> dict[str, object]:
    """One synthetic stack result with every key of the real one (values are placeholders)."""
    return {
        "max_concentration": hq,
        "max_concentration_1h": hq,
        "distance_m": 500.0,
        "stability_class": "D",
        "wind_speed": 3.0,
        "effective_release_height": 20.0,
        "hq": hq,
        "cancer_risk": risk,
        "stack_source": params["source"],
        "add": None,
        "add_band": None,
        "add_by_band": {},
        "representative": {"hq": hq / 2},
        "warnings": [],
        "stack_number": number,
        "stack_height": params["stack_height"],
        "stack_diameter": params["stack_diameter"],
        "exit_velocity": params["exit_velocity"],
        "exit_temperature": params["exit_temperature"],
    }


def exposure_of(
    rate: float,
    stacks: list[StackParameters],
    temperature: float,
    toxicity: Toxicity,
) -> FacilityExposure:
    """Synthetic results: concentration = HQ, cancer risk = HQ x 1e-6 when there is an IUR."""
    hqs = [hq_of(rate, s["stack_height"] or 1.0, temperature) for s in stacks]
    has_rfc, has_iur = toxicity["rfc"] is not None, toxicity["iur"] is not None
    results = [
        _result(number, params, hq, hq * 1e-6 if has_iur else None)
        for number, (params, hq) in enumerate(zip(stacks, hqs, strict=True), start=1)
    ]
    hq = _entry(hqs) if hqs and has_rfc else None
    risk = _entry([h * 1e-6 for h in hqs]) if hqs and has_iur else None
    conc = _entry(hqs) if hqs else None
    representative = {"max_concentration": conc, "hq": hq, "cancer_risk": risk}
    ranges = {
        "max_concentration": conc,
        "hq": hq,
        "cancer_risk": risk,
        "representative": representative,
    }
    return cast(
        FacilityExposure,
        {
            "results": results,
            "range": ranges if hqs else None,
            "stacks_given": len(stacks),
            "stacks_evaluated": len(stacks),
            "warnings": ["synthetic facility note"],
        },
    )


@dataclass
class FakeSteps:
    """Scripted steps that log every call; unknown inputs get empty answers."""

    nei_stacks: dict[str, list[StackParameters]] = field(
        default_factory=dict[str, list[StackParameters]],
    )
    titles: dict[str, str | None] = field(default_factory=dict[str, str | None])
    matches: list[SccMatch] = field(default_factory=list[SccMatch])
    pstk_rows: dict[str, StackParameters] = field(default_factory=dict[str, StackParameters])
    calls: list[tuple[str, object]] = field(default_factory=list[tuple[str, object]])

    def nei(self, frs_id: str, eis_ids: list[str]) -> NeiStackResult:
        self.calls.append(("nei", (frs_id, tuple(eis_ids))))
        found = self.nei_stacks.get(frs_id, [])
        return NeiStackResult(
            eis_ids=eis_ids,
            candidates=found,
            total_candidates=len(found),
            warnings=[],
        )

    def industry(self, doc: str) -> FacilityIndustry:
        self.calls.append(("industry", doc))
        title = self.titles.get(doc)
        return FacilityIndustry(
            naics_code="111111" if title else None,
            naics_title=title,
            code_origin=None,
            source="Synthetic",
            warnings=[],
        )

    def scc(self, title: str) -> SccLookupResult:
        self.calls.append(("scc", title))
        return SccLookupResult(matches=self.matches, warnings=[])

    def pstk(self, scc: str | None) -> StackParameters:
        self.calls.append(("pstk", scc))
        return self.pstk_rows.get(scc or "", GLOBAL)

    def weather(self, lat: float, lon: float, year: int | None) -> Meteorology:
        self.calls.append(("weather", (lat, lon, year)))
        return WEATHER

    def people(self, lat: float, lon: float, km: float | None) -> Population:
        self.calls.append(("people", km))
        return PEOPLE

    def exposure(
        self,
        rate: float,
        stacks: list[StackParameters],
        weather: Meteorology,
        people: Population,
        toxicity: Toxicity,
    ) -> FacilityExposure:
        self.calls.append(("exposure", (rate, len(stacks), weather["ambient_temperature"])))
        return exposure_of(rate, stacks, weather["ambient_temperature"], toxicity)

    def prefetch(self, titles: Sequence[str]) -> None:
        self.calls.append(("prefetch", tuple(titles)))

    def steps(self) -> Steps:
        return Steps(
            self.nei,
            self.industry,
            self.scc,
            self.pstk,
            self.weather,
            self.people,
            self.exposure,
            self.prefetch,
        )
