"""Settings routes: the API-key vaults and the display settings. Thin handlers only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from api.core.session_guard import current_user, require_admin_action
from api.dependencies import get_service_keys, get_settings
from api.schemas.settings import (
    ClientConfig,
    InitialView,
    KeysStatusResponse,
    KeyStatusResponse,
    KeyUpdatePayload,
    LayoutConfig,
    MapConfig,
    Thresholds,
    WorkerThresholds,
)
from app.key_vault import KeyStatus, ServiceKeys
from config.agent import get_agent_settings
from config.occupational import get_occupational_settings
from config.ui import KeyName, UiSettings

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
    dependencies=[Depends(current_user)],
)
# Display settings every visitor needs, the sign-in screen included: no session required.
public_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
Keys = Annotated[ServiceKeys, Depends(get_service_keys)]
Settings = Annotated[UiSettings, Depends(get_settings)]
# One entry per key: its name and the path segment of its routes.
KEY_PATHS: dict[KeyName, str] = {
    "openai": "openai-key",
    "census": "census-key",
    "comptox": "comptox-key",
}


def _status(status: KeyStatus) -> KeyStatusResponse:
    return KeyStatusResponse(configured=status.configured)


def _status_endpoint(name: KeyName) -> Callable[[Keys], KeyStatusResponse]:
    def key_status(keys: Keys) -> KeyStatusResponse:
        """Whether the key is stored; never any part of it."""
        return _status(keys.vault(name).status())

    return key_status


def _save_endpoint(name: KeyName) -> Callable[[KeyUpdatePayload, Keys], KeyStatusResponse]:
    def save_key(payload: KeyUpdatePayload, keys: Keys) -> KeyStatusResponse:
        """Store the key in the OS keychain."""
        return _status(keys.vault(name).save(payload.api_key.get_secret_value()))

    return save_key


def _clear_endpoint(name: KeyName) -> Callable[[Keys], KeyStatusResponse]:
    def clear_key(keys: Keys) -> KeyStatusResponse:
        """Remove the key from the OS keychain."""
        return _status(keys.vault(name).clear())

    return clear_key


def _add_key_routes(name: KeyName, path: str) -> None:
    """Status for every signed-in user; save and clear only for administrators, because the
    keys are the server's and every user's turns run with them."""
    admin = [Depends(require_admin_action)]
    for method, endpoint, guard in (
        ("GET", _status_endpoint(name), []),
        ("POST", _save_endpoint(name), admin),
        ("DELETE", _clear_endpoint(name), admin),
    ):
        router.add_api_route(
            f"/{path}",
            endpoint,
            methods=[method],
            response_model=KeyStatusResponse,
            name=f"{method.lower()}_{name}_key",
            dependencies=guard,
        )


for _name, _path in KEY_PATHS.items():
    _add_key_routes(_name, _path)


@router.get("/keys")
def all_keys_status(keys: Keys) -> KeysStatusResponse:
    """The status of every key at once (never a key)."""
    statuses = keys.statuses()
    return KeysStatusResponse(
        openai=_status(statuses["openai"]),
        census=_status(statuses["census"]),
        comptox=_status(statuses["comptox"]),
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


def _worker_thresholds() -> WorkerThresholds:
    t = get_occupational_settings().thresholds
    return WorkerThresholds(
        ratio_exceedance=t.exceedance_ratio,
        ratio_elevated=t.elevated_ratio,
        hq_exceedance=t.exceedance_hq,
        hq_elevated=t.elevated_hq,
        cancer_exceedance=t.exceedance_cancer_risk,
        cancer_elevated=t.elevated_cancer_risk,
    )


@public_router.get("/client")
def client_config(settings: Settings) -> ClientConfig:
    """Display settings the frontend needs."""
    limits, display = settings.thresholds, settings.display
    return ClientConfig(
        model=get_agent_settings().model,
        thresholds=Thresholds(
            hq_concern=limits.hq_concern,
            hq_near_lower=limits.hq_near_lower,
            cancer_lower=limits.cancer_lower,
            cancer_upper=limits.cancer_upper,
        ),
        worker_thresholds=_worker_thresholds(),
        map=_map_config(settings),
        significant_digits=display.significant_digits,
        narrow_breakpoint_px=display.narrow_breakpoint_px,
        layout=_layout_config(settings),
        suggestions=list(display.suggestions),
    )
