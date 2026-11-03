"""A synthetic assessed workspace and helpers to read a built report back as text.

Every number below is a placeholder chosen to be easy to trace in the output, not data.
"""

from __future__ import annotations

from io import BytesIO

import docx
from docx.document import Document
from docx.table import Table

from api.schemas.workspace import (
    Chemical,
    ConditionOfUse,
    ExposureRanges,
    Extreme,
    Extremum,
    Facility,
    Industry,
    Meteorology,
    ReadAcross,
    Receptors,
    RiskSummary,
    Screening,
    Stack,
    Unattributed,
    WorkspaceState,
)
from api.services.report.builder import report_context
from api.services.report.document import ReportContext
from config.ui import get_ui_settings


def context() -> ReportContext:
    """The report context of the shipped settings."""
    return report_context(get_ui_settings())


def chemical() -> Chemical:
    return Chemical(
        cas_number="11-11-1",
        name="Testium",
        molecular_weight_g_mol=11.5,
        rfc_mg_m3=0.25,
        iur_per_ug_m3=None,
        sources={"molecular_weight": "Source M", "rfc": "Source R"},
        read_across=ReadAcross(
            kind="read_across",
            surrogate_cas="2-22-2",
            surrogate_name="Surrogatium",
            hybrid_score=0.75,
            cosine_similarity=0.5,
            tanimoto_similarity=0.25,
            within_applicability_domain=True,
            warnings=["read-across note"],
        ),
        warnings=["IUR missing"],
    )


def facility(frs_id: str = "110000000001", *, defaults: bool = True) -> Facility:
    return Facility(
        frs_id=frs_id,
        name="Plant A",
        city="Town",
        state="TX",
        latitude=30.0,
        longitude=-95.0,
        medium="Air stack",
        reporting_year=2023,
        total_release=1234.5,
        release_unit="lb",
        emission_rate_g_s=0.125,
        operating_hours_per_year=8760.0,
        operating_hours_source="Source H",
        conditions_of_use=[
            ConditionOfUse(
                tri_activity="Produce",
                tri_section="3.1",
                lifecycle_stage="Manufacturing",
                cou_category="Domestic manufacturing",
                mapping_strength="direct",
            ),
        ],
        industry=Industry(naics_code="325199", naics_title="Chemicals", source="Source N"),
        stacks=[
            Stack(
                stack_number=1,
                height_m=15.0,
                diameter_m=1.5,
                exit_velocity_m_s=12.5,
                exit_temperature_k=350.0,
                source="Source S",
                tier=1,
                tier_label="Tier 1: Empirical NEI",
                warnings=["stack note"],
            ),
        ],
        receptors=Receptors(
            total_population=12345,
            radius_km=5.0,
            age_distribution={},
            source="Source P",
            screening_default=False,
        ),
        meteorology=Meteorology(
            wind_speed_m_s=2.5,
            wind_from_deg=225.0,
            wind_toward_deg=45.0,
            ambient_temperature_k=290.0,
            stability_class="D",
            source="Source W",
            screening_default=defaults,
            latitude=30.0,
            longitude=-95.0,
            frs_id=frs_id,
        ),
        exposure=ExposureRanges(
            stacks_given=1,
            stacks_evaluated=1,
            hq_worst=Extreme(low=0.375, high=0.375, low_stack=1, high_stack=1),
            cancer_risk_worst=Extreme(low=2.5e-5, high=2.5e-5, low_stack=1, high_stack=1),
            concentration_worst=Extreme(low=7.5, high=7.5, low_stack=1, high_stack=1),
        ),
        status="near",
        screening=Screening(outcome="full", value_hq=0.375, value_cancer_risk=2.5e-5),
    )


def assessed() -> WorkspaceState:
    """One fully assessed facility with a chemical, read-across and warnings."""
    plant = facility()
    return WorkspaceState(
        facilities=[plant],
        selected_frs_id=plant.frs_id,
        chemical=chemical(),
        risk=RiskSummary(
            hq_worst=Extremum(
                value=0.375,
                frs_id=plant.frs_id,
                facility_name="Plant A",
                stack_number=1,
                status="near",
            ),
            cancer_risk_worst=Extremum(
                value=2.5e-5,
                frs_id=plant.frs_id,
                facility_name="Plant A",
                stack_number=1,
                status="near",
            ),
        ),
        unattributed=[Unattributed(tool="some_tool", reason="two facilities matched")],
        warnings=["a result was left out"],
    )


def chemical_only() -> WorkspaceState:
    """A chemical result and no facility."""
    return WorkspaceState(chemical=chemical())


def load(data: bytes) -> Document:
    return docx.Document(BytesIO(data))


def _table_lines(grid: Table) -> list[str]:
    return [" | ".join(cell.text for cell in row.cells) for row in grid.rows]


def lines(doc: Document) -> list[str]:
    """Every paragraph and table row of the body, in document order."""
    out: list[str] = []
    for block in doc.iter_inner_content():
        if isinstance(block, Table):
            out.extend(_table_lines(block))
        elif block.text.strip():
            out.append(block.text)
    return out


def headings(doc: Document) -> list[str]:
    """The level-1 headings, in order."""
    return [p.text for p in doc.paragraphs if p.style is not None and p.style.name == "Heading 1"]
