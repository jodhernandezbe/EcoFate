"""Synthetic inputs for the worker screening tests (round numbers, never data about a facility)."""

from __future__ import annotations

from pathlib import Path

from config.ecetoc_tra import get_ecetoc_tra_settings
from config.occupational import get_occupational_settings
from config.osha_cehd import get_osha_cehd_settings
from tests.tools.assessment.factories import record
from tools.assessment.helpers.activities.crosswalk import Crosswalk, ScenarioRow
from tools.assessment.helpers.monitoring.cehd import MonitoringTable, load_table
from tools.assessment.helpers.occupational import Sources, Workplace
from tools.assessment.helpers.occupational_bands.ecetoc import load_table as load_tra
from tools.schemas import (
    CdrSector,
    EmissionRecord,
    OccupationalLimits,
    OperationalProfile,
    Toxicity,
)

SETTINGS = get_occupational_settings()
CAS = "000-00-0"
TOX = Toxicity(rfc=1.0, iur=1e-6)
HEADER = "imis,naics_prefix,unit,n,n_nd,median,p95,first_year,last_year\n"
SECTOR = CdrSector(
    code="IS99",
    name="Synthetic sector",
    matched_naics_prefix="3",
    naics_edition="2017",
)


def limits(oel: float | None = 5.0) -> OccupationalLimits:
    return OccupationalLimits(
        oel_twa_mg_m3=oel,
        oel_source=None if oel is None else "OSHA PEL-TWA (PubChem)",
        limits={},
        reasons={},
        warnings=[],
    )


def workplace(
    *,
    oel: float | None = 5.0,
    pressure: float | None = 10.0,
    weight: float | None = 100.0,
    cas: str | None = None,
) -> Workplace:
    """A chemical of 100 g/mol and 10 mmHg unless told otherwise."""
    return Workplace(
        SETTINGS,
        limits(oel),
        cas,
        weight,
        None if weight is None else "CompTox",
        pressure,
        None if pressure is None else "CompTox (experimental)",
    )


def profile(
    stages: tuple[str, ...] = ("Manufacturing",),
    *,
    days: float | None = 250.0,
    sector: bool = False,
) -> OperationalProfile:
    return OperationalProfile(
        naics_code="325199",
        life_cycle_stage=list(stages),
        cou_category=[],
        cdr_sector=SECTOR if sector else None,
        days_per_week=5,
        operating_days_per_year=days,
        hours_per_day=16.0,
        annual_operating_hours=None if days is None else days * 16.0,
        schedule_source="test",
        warnings=[],
    )


def release(kg: float | None = 1000.0) -> EmissionRecord:
    return record(fugitive_release_kg_per_year=kg, fugitive_reporting_year=2020)


def row(stage: str, scenario: str, *activities: str) -> ScenarioRow:
    return ScenarioRow(1, "IS99", stage, scenario, "published ESD", activities, "p1", "A source")


def monitoring(tmp_path: Path, rows: list[str]) -> MonitoringTable:
    """A one-substance table (CAS 000-00-0 is OSHA code AAAA) from synthetic rows."""
    summary, crosswalk = tmp_path / "s.csv", tmp_path / "c.csv"
    summary.write_text("# synthetic window\n" + HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    crosswalk.write_text(
        f"imis_code,cas,substance,source\nAAAA,{CAS},SYNTHETIC,x\n",
        encoding="utf-8",
    )
    return load_table(summary, crosswalk)


def sources(
    rows: tuple[ScenarioRow, ...] = (),
    table: MonitoringTable | None = None,
) -> Sources:
    tra = get_ecetoc_tra_settings()
    return Sources(Crosswalk(rows), load_tra(tra.table_path), tra, get_osha_cehd_settings(), table)
