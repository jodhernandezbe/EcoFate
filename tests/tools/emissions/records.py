"""Synthetic emission records for tests (round numbers, never real measurements)."""

from __future__ import annotations

from tools.schemas import EmissionRecord


def emission_record(
    frs_id: str,
    rate: float,
    state: str | None = "TX",
    city: str | None = "Houston",
) -> EmissionRecord:
    return {
        "frs_id": frs_id,
        "facility_name": frs_id,
        "environmental_medium": "AIR STACK",
        "reporting_year": 2020,
        "doc_ctrl_num": None,
        "naics_code": None,
        "naics_title": None,
        "naics_subsector": None,
        "naics_subsector_title": None,
        "eis_ids": [],
        "eis_note": None,
        "total_release": 1.0,
        "unit": "Pounds",
        "emission_rate": rate,
        "operating_hours_per_year": 8760.0,
        "operating_hours_source": "default 8760 h/yr (configured)",
        "fugitive_release_kg_per_year": None,
        "fugitive_reporting_year": None,
        "conditions_of_use": [],
        "lifecycle_stages": [],
        "conditions_note": None,
        "latitude": 10.0,
        "longitude": -20.0,
        "address": None,
        "city": city,
        "county": None,
        "state": state,
        "zip_code": None,
    }
