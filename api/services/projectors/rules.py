"""The configured values the workspace needs to attribute results and to grade risk."""

from __future__ import annotations

from dataclasses import dataclass

from api.schemas.workspace import Status
from commons.bands import BANDS, Band, band_of
from config.exposure_graph import GraphText
from config.risk_bands import RiskBands


@dataclass(frozen=True)
class WorkspaceRules:
    """Band boundaries, the tolerance for matching points to facilities and the default radius.

    Attributes:
        thresholds: Boundaries of the screening bands (unitless; cancer risk is a probability).
        coordinate_tolerance_deg: Tolerance for matching a queried point to a facility, degrees.
        default_radius_km: Receptor radius of a population call that gave none, km.
        sector_half_angle_deg: Half-angle of the schematic downwind sector, degrees.
        vertex_spacing_deg: Angular spacing of the vertices of the drawn shapes, degrees.
        graph: Fixed text and units of the exposure graph.
    """

    thresholds: RiskBands
    coordinate_tolerance_deg: float
    default_radius_km: float
    sector_half_angle_deg: float
    vertex_spacing_deg: float
    graph: GraphText


def hq_status(value: float, thresholds: RiskBands) -> Status:
    """The band of a hazard quotient (unitless)."""
    return band_of(value, thresholds.hq_lower, thresholds.hq_upper)


def cancer_status(value: float, thresholds: RiskBands) -> Status:
    """The band of a lifetime cancer risk (probability)."""
    return band_of(value, thresholds.cancer_risk_lower, thresholds.cancer_risk_upper)


def worse(first: Status | None, second: Status | None) -> Status | None:
    """The higher of two bands; None when neither is known."""
    known: list[Band] = [s for s in (first, second) if s is not None]
    return max(known, key=BANDS.index) if known else None
