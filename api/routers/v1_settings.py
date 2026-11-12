"""Settings routes: the signed-in user's OpenAI key, data-service availability and the display
settings. Thin handlers only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.core.session_guard import CurrentUser, current_user
from api.dependencies import get_key_services, get_settings
from api.schemas.settings import (
    BandBoundaries,
    ClientConfig,
    InitialView,
    KeysStatusResponse,
    KeyStatusResponse,
    KeyUpdatePayload,
    LayoutConfig,
    MapConfig,
    ServiceAvailability,
    ServicesAvailability,
)
from api.services.key_setup import KeyServices
from app.key_vault import KeyStatus
from config.agent import get_agent_settings
from config.risk_bands import get_risk_bands
from config.ui import UiSettings

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
    dependencies=[Depends(current_user)],
)
# Display settings every visitor needs, the sign-in screen included: no session required.
public_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
Settings = Annotated[UiSettings, Depends(get_settings)]
Keys = Annotated[KeyServices, Depends(get_key_services)]


def _status(status: KeyStatus) -> KeyStatusResponse:
    return KeyStatusResponse(configured=status.configured)


@router.get("/openai-key")
async def openai_key_status(user: CurrentUser, keys: Keys) -> KeyStatusResponse:
    """Whether the signed-in user has an OpenAI key stored; never any part of it."""
    return _status(await keys.vault.status(user.id))


@router.post("/openai-key")
async def save_openai_key(
    payload: KeyUpdatePayload,
    user: CurrentUser,
    keys: Keys,
) -> KeyStatusResponse:
    """Seal the user's OpenAI key in the database (encrypted, bound to their account)."""
    return _status(await keys.vault.save(user.id, payload.api_key.get_secret_value()))


@router.delete("/openai-key")
async def clear_openai_key(user: CurrentUser, keys: Keys) -> KeyStatusResponse:
    """Delete the user's stored OpenAI key."""
    return _status(await keys.vault.clear(user.id))


@router.get("/keys")
async def all_keys_status(user: CurrentUser, keys: Keys) -> KeysStatusResponse:
    """The user's OpenAI key status and which data services this installation provides."""
    available = keys.operator.available()
    return KeysStatusResponse(
        openai=_status(await keys.vault.status(user.id)),
        services=ServicesAvailability(
            census=ServiceAvailability(available=available["census"]),
            comptox=ServiceAvailability(available=available["comptox"]),
        ),
    )


def _map_config(settings: UiSettings) -> MapConfig:
    shown = settings.map
    return MapConfig(
        light_style=shown.light_style,
        dark_style=shown.dark_style,
        marker_min_px=shown.marker_min_px,
        marker_max_px=shown.marker_max_px,
        initial_view=InitialView(**vars(shown.initial_view)),
    )


def _layout_config(settings: UiSettings) -> LayoutConfig:
    shown = settings.layout
    return LayoutConfig.model_validate(
        {
            "rail": vars(shown.rail),
            "chat": vars(shown.chat),
            "overview": vars(shown.overview),
        },
    )


def _band_boundaries() -> BandBoundaries:
    return BandBoundaries(**vars(get_risk_bands()))


@public_router.get("/client")
def client_config(settings: Settings) -> ClientConfig:
    """Display settings the frontend needs."""
    display = settings.display
    return ClientConfig(
        model=get_agent_settings().model,
        bands=_band_boundaries(),
        map=_map_config(settings),
        significant_digits=display.significant_digits,
        narrow_breakpoint_px=display.narrow_breakpoint_px,
        layout=_layout_config(settings),
        suggestions=list(display.suggestions),
    )
