"""Settings contract: the user's key status and the display settings sent to the frontend."""

from __future__ import annotations

from pydantic import Field, SecretStr

from api.schemas.base import ContractModel


class KeyUpdatePayload(ContractModel):
    """Body of ``POST /api/v1/settings/openai-key``; the key is never echoed or logged."""

    api_key: SecretStr = Field(
        description="The user's OpenAI API key; stored encrypted for their account only.",
    )


class KeyStatusResponse(ContractModel):
    """Whether a key is stored; never the key or any part of it."""

    configured: bool


class ServiceAvailability(ContractModel):
    """Whether a data service is provided by this installation (never its key)."""

    available: bool


class ServicesAvailability(ContractModel):
    """The data services the operator may provide."""

    census: ServiceAvailability
    comptox: ServiceAvailability


class KeysStatusResponse(ContractModel):
    """The user's OpenAI key status and the data services this installation provides."""

    openai: KeyStatusResponse
    services: ServicesAvailability


class BandBoundaries(ContractModel):
    """Boundaries of the screening bands, the same for community and worker results.

    A value from `*_lower` is "moderate", from `*_upper` "high"; a value on a boundary goes to
    the higher band. Hazard quotient and limit ratio are unitless; cancer risk is a probability.
    """

    hq_lower: float
    hq_upper: float
    cancer_risk_lower: float
    cancer_risk_upper: float
    oel_ratio_lower: float
    oel_ratio_upper: float


class InitialView(ContractModel):
    """A box on the map, decimal degrees (WGS84, west negative)."""

    west: float
    south: float
    east: float
    north: float


class MapConfig(ContractModel):
    """Basemap style URLs and the marker radii (px) for the smallest and largest emission rate."""

    light_style: str
    dark_style: str
    marker_min_px: float
    marker_max_px: float
    initial_view: InitialView = Field(description="What the map shows before any facility.")


class RailLayout(ContractModel):
    """Navigation rail widths in px: collapsed to icons, and the expanded default and limits."""

    collapsed_px: int
    default_px: int
    min_px: int
    max_px: int


class ChatLayout(ContractModel):
    """Chat dock: default and maximum shares of the viewport width (0-1), minimum width in px."""

    default_share: float
    min_px: int
    max_share: float


class OverviewLayout(ContractModel):
    """Overview panel height as shares (0-1) of the analysis area."""

    default_share: float
    min_share: float
    max_share: float


class LayoutConfig(ContractModel):
    """Workspace layout limits from the configuration."""

    rail: RailLayout
    chat: ChatLayout
    overview: OverviewLayout


class ClientConfig(ContractModel):
    """Display settings the frontend needs (``GET /api/v1/settings/client``)."""

    model: str = Field(description="Chat model that drives the agent.")
    bands: BandBoundaries
    map: MapConfig
    significant_digits: int
    narrow_breakpoint_px: int
    layout: LayoutConfig
    suggestions: list[str]
