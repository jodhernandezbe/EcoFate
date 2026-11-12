"""Synthetic tool exchanges for workspace tests (round numbers, never real measurements)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from api.services.projectors.rules import WorkspaceRules
from config.risk_bands import RiskBands
from config.ui import get_ui_settings

RULES = WorkspaceRules(
    thresholds=RiskBands(
        hq_lower=0.1,
        hq_upper=1.0,
        cancer_risk_lower=1e-6,
        cancer_risk_upper=1e-4,
        oel_ratio_lower=0.1,
        oel_ratio_upper=1.0,
    ),
    coordinate_tolerance_deg=1e-3,
    default_radius_km=2.0,
    sector_half_angle_deg=20.0,
    vertex_spacing_deg=10.0,
    graph=get_ui_settings().exposure_graph,
)
_ids = itertools.count(1)


def exchange(
    name: str,
    args: Mapping[str, object],
    result: object,
    *,
    status: str = "success",
    artifact: object = None,
) -> list[BaseMessage]:
    """An assistant tool call and the tool message answering it (a str result is sent as is)."""
    call_id = f"call_{next(_ids)}"
    content = result if isinstance(result, str) else json.dumps(result)
    return [
        AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": dict(args)}]),
        ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=name,
            artifact=artifact,
            status="error" if status == "error" else "success",
        ),
    ]


def record(
    frs_id: str = "F1",
    lat: float = 10.0,
    lon: float = -20.0,
    rate: float = 1.0,
    **extra: object,
) -> dict[str, object]:
    """One inventory record."""
    return {
        "frs_id": frs_id,
        "facility_name": f"Plant {frs_id}",
        "environmental_medium": "AIR STACK",
        "reporting_year": 2020,
        "doc_ctrl_num": f"DOC{frs_id}",
        "naics_subsector": "325",
        "naics_subsector_title": "Chemical Manufacturing",
        "total_release": 100.0,
        "unit": "Pounds",
        "emission_rate": rate,
        "operating_hours_per_year": 8760.0,
        "operating_hours_source": "default 8760 h/yr (test)",
        "latitude": lat,
        "longitude": lon,
        "address": "1 Test Road",
        "city": "Testville",
        "county": "Test",
        "state": "TX",
        "zip_code": "00000",
        **extra,
    }


def inventory(*records: dict[str, object], cas: str = "1-1-1") -> list[BaseMessage]:
    return exchange("query_emissions_inventory", {"cas_number": cas}, list(records))


def capped_inventory(
    *records: dict[str, object],
    shown: int,
    cas: str = "1-1-1",
) -> list[BaseMessage]:
    """An inventory as the tool sends it: the model reads ``shown`` records, the program all."""
    listed = {
        "total_found": len(records),
        "matching": len(records),
        "shown": shown,
        "facilities": list(records[:shown]),
        "note": "partial",
    }
    return exchange(
        "query_emissions_inventory",
        {"cas_number": cas},
        listed,
        artifact=list(records),
    )


def stack(
    height: float | None = 10.0,
    source: str | None = "NEI",
    scc: str | None = None,
) -> dict[str, object]:
    """One stack as the stack tools return it (all four values set, or all None)."""
    given = height is not None
    return {
        "stack_height": height,
        "stack_diameter": 1.0 if given else None,
        "exit_velocity": 2.0 if given else None,
        "exit_temperature": 300.0 if given else None,
        "source": source,
        "scc": scc,
        "warnings": [],
    }


def scenario(hq: float | None, risk: float | None, conc: float | None = 5.0) -> dict[str, object]:
    return {
        "max_concentration": conc,
        "distance_m": 100.0,
        "hq": hq,
        "cancer_risk": risk,
    }


def stack_result(
    number: int,
    base: dict[str, object],
    worst: dict[str, object],
    rep: dict[str, object],
) -> dict[str, object]:
    """One per-stack exposure result echoing its stack."""
    return {
        **worst,
        "stack_number": number,
        "stack_height": base["stack_height"],
        "stack_diameter": base["stack_diameter"],
        "exit_velocity": base["exit_velocity"],
        "exit_temperature": base["exit_temperature"],
        "stack_source": base["source"],
        "representative": rep,
        "warnings": [],
    }


def entry(low: float, high: float, low_stack: int = 1, high_stack: int = 1) -> dict[str, object]:
    return {"low": low, "high": high, "low_stack": low_stack, "high_stack": high_stack}


def exposure(
    rate: float,
    results: list[dict[str, object]],
    hq: dict[str, object] | None,
    risk: dict[str, object] | None = None,
) -> list[BaseMessage]:
    """An exposure call with the range of the given worst-case HQ and cancer-risk entries."""
    rng = {
        "max_concentration": None,
        "hq": hq,
        "cancer_risk": risk,
        "representative": {"max_concentration": None, "hq": hq, "cancer_risk": risk},
    }
    body: dict[str, object] = {
        "results": results,
        "range": rng if results else None,
        "stacks_given": len(results),
        "stacks_evaluated": len(results),
        "warnings": [],
    }
    return exchange("calculate_exposure_metrics", {"emission_rate": rate}, body)


def weather(
    lat: float = 10.0,
    lon: float = -20.0,
    source: str = "synthetic 2020",
) -> list[BaseMessage]:
    body: dict[str, object] = {
        "wind_speed": 3.0,
        "wind_direction": 270.0,
        "stability_class": "D",
        "ambient_temperature": 290.0,
        "source": source,
        "warnings": [],
    }
    return exchange("get_meteorological_boundary", {"latitude": lat, "longitude": lon}, body)


def people(
    lat: float = 10.0,
    lon: float = -20.0,
    radius: float | None = 3.0,
    source: str = "synthetic ACS",
) -> list[BaseMessage]:
    body: dict[str, object] = {
        "total_population": 1000,
        "age_distribution": {"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0},
        "source": source,
        "warnings": [],
    }
    args: dict[str, object] = {"latitude": lat, "longitude": lon}
    if radius is not None:
        args["radius_km"] = radius
    return exchange("get_population_receptors", args, body)


def activity_case(**over: object) -> dict[str, object]:
    """One output of a modelled worker activity (synthetic round numbers)."""
    return {
        "estimator": "mass_balance",
        "airflow_m3_per_s": 1.0,
        "mixing_factor": 0.5,
        "room_m3": None,
        "air_exchange_per_h": None,
        "generation_g_per_s": 0.25,
        "concentration_mg_m3": 4.0,
        "capped": False,
        "twa_mg_m3": 2.0,
        **over,
    }


def worker_case(**over: object) -> dict[str, object]:
    """One case (baseline or worst) of a worker result."""
    return {
        "setting": "indoor",
        "estimator": "mass_balance",
        "airflow_m3_per_s": 1.0,
        "mixing_factor": 0.5,
        "room_m3": None,
        "air_exchange_per_h": None,
        "generation_g_per_s": 0.25,
        "workplace_concentration_mg_m3": 4.0,
        "capped": False,
        "twa_mg_m3": 2.0,
        "oel_ratio": 0.4,
        "hq": 0.2,
        "cancer_risk": 3e-6,
        "risk_tier": "moderate",
        **over,
    }


def worker_result(**over: object) -> dict[str, object]:
    """A worker result resting on the activity model, with one driving activity."""
    drum = {
        "key": "drum_loading",
        "label": "Drum loading",
        "model": "ap42_loading",
        "setting": "indoor",
        "hours": 2.0,
        "typical": activity_case(),
        "worst_case": activity_case(estimator="two_zone", room_m3=50.0, air_exchange_per_h=4.0),
        "warnings": ["a synthetic activity warning"],
        "statement": None,
    }
    return {
        "evidence": "activity_model",
        "molecular_weight": 100.0,
        "molecular_weight_source": "synthetic source",
        "vapor_pressure_mmhg": 10.0,
        "vapor_pressure_source": "synthetic pressure",
        "volatility": "within",
        "operating_days_per_year": 250.0,
        "hours_per_day": 16.0,
        "oel_twa_mg_m3": 5.0,
        "oel_source": "OSHA PEL-TWA (PubChem)",
        "rfc": 1.0,
        "iur": 1e-6,
        "fugitive_release_kg_per_year": 1000.0,
        "fugitive_reporting_year": 2020,
        "fugitive_statement": "context only; no worker value uses it",
        "driving_activity": {
            **{k: drum[k] for k in ("key", "label", "model", "setting", "hours", "statement")},
            "estimator": "two_zone",
        },
        "activities": [drum],
        "activity_reason": None,
        "routes": [
            {
                "stage": "Processing",
                "generic_operation": ["drum_loading"],
                "scenarios": [
                    {
                        "title": "Synthetic scenario",
                        "category": "published ESD",
                        "pages": "pp. 1-2",
                        "source": "synthetic citation",
                        "activities": ["drum_loading"],
                    },
                ],
                "note": None,
            },
        ],
        "monitoring": None,
        "monitoring_reason": "no samples for the industry",
        "baseline": worker_case(),
        "worst_case": worker_case(
            estimator="two_zone",
            airflow_m3_per_s=None,
            mixing_factor=None,
            room_m3=50.0,
            air_exchange_per_h=4.0,
            oel_ratio=2.0,
            risk_tier="high",
        ),
        "risk_tier": "moderate",
        "assumptions": ["a well-mixed zone"],
        "warnings": [],
        **over,
    }


def monitoring_result(**over: object) -> dict[str, object]:
    """A worker result resting on OSHA's measured samples (no modelled activity)."""
    sampled = worker_case(
        setting=None,
        estimator="monitoring",
        airflow_m3_per_s=None,
        mixing_factor=None,
        generation_g_per_s=None,
        workplace_concentration_mg_m3=None,
        capped=None,
    )
    return worker_result(
        evidence="monitoring",
        driving_activity=None,
        activities=[],
        activity_reason="measured samples were used instead",
        monitoring={
            "imis_code": "1234",
            "naics_level": "4-digit NAICS",
            "n_values": 40,
            "n_nondetect": 5,
            "median_mg_m3": 1.5,
            "p95_mg_m3": 6.0,
            "first_year": 2005,
            "last_year": 2020,
            "reason": None,
            "source": "OSHA CEHD (synthetic)",
            "statements": ["a synthetic monitoring statement"],
        },
        monitoring_reason=None,
        baseline=sampled,
        worst_case={**sampled, "twa_mg_m3": 6.0, "oel_ratio": 1.2, "risk_tier": "high"},
        **over,
    )
