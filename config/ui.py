"""Typed loader for the ``[ui]`` settings: the local web backend and its display settings."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypedDict, get_args

from config.exposure_graph import GraphText, parse_exposure_graph
from config.parsing import (
    as_table,
    names,
    project_path,
    read_toml,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)
from config.report import ReportSettings, parse_report

_NAME = "ui"
# The keys the interface can store: the model provider and the two services the tools call.
KeyName = Literal["openai", "census", "comptox"]
KEY_NAMES: tuple[KeyName, ...] = get_args(KeyName)
_MAX_PORT = 65535
_MAX_HALF_ANGLE_DEG = 90.0


@dataclass(frozen=True)
class KeyringNames:
    """Credential-store entries holding the API keys (names only, never a key).

    Attributes:
        service: Service name shared by every entry.
        accounts: Key name -> account name of its entry.
    """

    service: str
    accounts: Mapping[KeyName, str]


@dataclass(frozen=True)
class ScopePrompts:
    """Guardrail prompt names (``prompts/<name>.md``) and their limits.

    Attributes:
        classifier: Prompt that classifies a turn and writes the redirect.
        addendum: Prompt appended to the agent system prompt in the web program.
        fallback: Redirect text used when the classifier gives none.
        history_window: Earlier messages the classifier sees besides the latest user message.
        completion: Prompt that reviews whether the agent's reply stopped early.
        nudge: Message that sends the agent back to work after such a reply.
        max_nudges: Most nudges in one user turn.
    """

    classifier: str
    addendum: str
    fallback: str
    history_window: int
    completion: str
    nudge: str
    max_nudges: int


@dataclass(frozen=True)
class MapBounds:
    """A box on the map, decimal degrees (WGS84, west negative)."""

    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True)
class MapDisplay:
    """Map settings.

    Attributes:
        light_style: Basemap style URL for light mode.
        dark_style: Basemap style URL for dark mode.
        sector_half_angle_deg: Half-angle of the schematic downwind sector, degrees.
        vertex_spacing_deg: Angular spacing of the vertices of the drawn circle and arc, degrees.
        marker_min_px: Marker radius for the smallest emission rate on screen, px.
        marker_max_px: Marker radius for the largest emission rate on screen, px.
        coordinate_tolerance_deg: Tolerance matching receptor queries to facilities, degrees.
        initial_view: What the map shows before any facility is placed.
    """

    light_style: str
    dark_style: str
    sector_half_angle_deg: float
    vertex_spacing_deg: float
    marker_min_px: float
    marker_max_px: float
    coordinate_tolerance_deg: float
    initial_view: MapBounds


@dataclass(frozen=True)
class RiskThresholds:
    """Status thresholds: HQ (unitless) and lifetime cancer risk (unitless probability).

    Attributes:
        hq_concern: HQ above this is "above" the threshold of concern.
        hq_near_lower: HQ from this up to ``hq_concern`` is "near".
        cancer_lower: Cancer risk below this is "below".
        cancer_upper: Cancer risk above this is "above"; in between is "near".
    """

    hq_concern: float
    hq_near_lower: float
    cancer_lower: float
    cancer_upper: float


@dataclass(frozen=True)
class Display:
    """Display settings: significant digits, narrow breakpoint (px) and suggestion chips."""

    significant_digits: int
    narrow_breakpoint_px: int
    suggestions: tuple[str, ...]


@dataclass(frozen=True)
class RailLayout:
    """Navigation rail widths, px: collapsed to icons, and the expanded default and limits."""

    collapsed_px: int
    default_px: int
    min_px: int
    max_px: int


@dataclass(frozen=True)
class ChatLayout:
    """Chat dock size: default and maximum as shares of the viewport width, minimum in px."""

    default_share: float
    min_px: int
    max_share: float


@dataclass(frozen=True)
class OverviewLayout:
    """Overview panel height as shares of the analysis area: default and limits."""

    default_share: float
    min_share: float
    max_share: float


@dataclass(frozen=True)
class Layout:
    """Workspace layout limits: the rail, the chat dock and the overview/map split."""

    rail: RailLayout
    chat: ChatLayout
    overview: OverviewLayout


@dataclass(frozen=True)
class ModelPrice:
    """Token prices of one chat model, USD per million tokens, with their provenance.

    Attributes:
        input_usd_per_mtok: Uncached input tokens.
        cached_input_usd_per_mtok: Cached input tokens.
        output_usd_per_mtok: Output tokens.
        priced_on: Date the prices were read from the provider's page.
        source_url: Page the prices were read from.
    """

    input_usd_per_mtok: float
    cached_input_usd_per_mtok: float
    output_usd_per_mtok: float
    priced_on: date
    source_url: str


@dataclass(frozen=True)
class UiSettings:
    """Web backend and display settings.

    Attributes:
        host: Loopback host the backend binds to, and the host of its origin.
        port: TCP port.
        container_bind_host: Address bound instead of ``host`` when launched in a container
            (loopback or unspecified); the origin stays ``host:port``.
        frontend_dist: Built frontend directory served by the backend.
        max_key_length: Longest API key accepted, characters.
        keyring: Credential-store names for the API key.
        prompts: Scope-guardrail prompts.
        step_labels: Tool name -> step label shown in the chat.
        map: Map settings.
        thresholds: Risk status thresholds.
        display: Digits, breakpoint and suggestion chips.
        layout: Workspace layout limits.
        max_threads: Most conversation threads held in memory.
        pricing: Chat model name -> token prices.
        report: Fixed text of the Word assessment report.
        exposure_graph: Fixed text and units of the exposure chain graph.
    """

    host: str
    port: int
    container_bind_host: str
    frontend_dist: Path
    max_key_length: int
    keyring: KeyringNames
    prompts: ScopePrompts
    step_labels: Mapping[str, str]
    map: MapDisplay
    thresholds: RiskThresholds
    display: Display
    layout: Layout
    max_threads: int
    pricing: Mapping[str, ModelPrice]
    report: ReportSettings
    exposure_graph: GraphText

    @property
    def origin(self) -> str:
        """The backend's own origin, e.g. ``http://127.0.0.1:8765``."""
        return f"http://{self.host}:{self.port}"


def _container_bind_host(table: dict[str, object]) -> str:
    name = f"{_NAME}.container"
    host = require_str(subtable(table, "container", _NAME), "bind_host", name).strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None or not (address.is_loopback or address.is_unspecified):
        raise ValueError(f"{name}.bind_host must be a loopback or unspecified address")
    return host


def _loopback_host(table: dict[str, object]) -> str:
    host = require_str(table, "host", _NAME).strip()
    if host == "localhost":
        return host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(f"{_NAME}.host must be a loopback address")
    return host


def _port(table: dict[str, object]) -> int:
    port = require_int(table, "port", minimum=1, name=_NAME)
    if port > _MAX_PORT:
        raise ValueError(f"{_NAME}.port must be between 1 and {_MAX_PORT}")
    return port


def _keyring(table: dict[str, object]) -> KeyringNames:
    name = f"{_NAME}.keyring"
    sub = subtable(table, "keyring", _NAME)
    accounts_name = f"{name}.accounts"
    accounts = subtable(sub, "accounts", name)
    values: dict[KeyName, str] = {
        key: require_str(accounts, key, accounts_name).strip() for key in KEY_NAMES
    }
    if len(set(values.values())) != len(values):
        raise ValueError(f"{accounts_name} must give each key its own account name")
    return KeyringNames(
        service=require_str(sub, "service", name).strip(),
        accounts=MappingProxyType(values),
    )


def _prompts(table: dict[str, object]) -> ScopePrompts:
    name = f"{_NAME}.prompts"
    sub = subtable(table, "prompts", _NAME)
    return ScopePrompts(
        classifier=require_str(sub, "scope_classifier", name).strip(),
        addendum=require_str(sub, "scope_addendum", name).strip(),
        fallback=require_str(sub, "scope_fallback", name).strip(),
        history_window=require_int(sub, "history_window", minimum=0, name=name),
        completion=require_str(sub, "completion_classifier", name).strip(),
        nudge=require_str(sub, "completion_nudge", name).strip(),
        max_nudges=require_int(sub, "max_nudges", minimum=0, name=name),
    )


def _step_labels(table: dict[str, object]) -> Mapping[str, str]:
    name = f"{_NAME}.step_labels"
    sub = subtable(table, "step_labels", _NAME)
    return MappingProxyType({key: require_str(sub, key, name).strip() for key in sub})


def _half_angle(sub: dict[str, object], name: str) -> float:
    value = require_number(sub, "sector_half_angle_deg", minimum=0.001, name=name)
    if value >= _MAX_HALF_ANGLE_DEG:
        raise ValueError(f"{name}.sector_half_angle_deg must be below {_MAX_HALF_ANGLE_DEG}")
    return value


def _spacing(sub: dict[str, object], name: str) -> float:
    value = require_number(sub, "vertex_spacing_deg", minimum=0.1, name=name)
    if value > _MAX_HALF_ANGLE_DEG:
        raise ValueError(f"{name}.vertex_spacing_deg must not exceed {_MAX_HALF_ANGLE_DEG}")
    return value


def _bound(sub: dict[str, object], key: str, limit: float, name: str) -> float:
    value = require_number(sub, key, minimum=-limit, name=name)
    if value > limit:
        raise ValueError(f"{name}.{key} must be between {-limit} and {limit}")
    return value


def _initial_view(sub: dict[str, object], parent: str) -> MapBounds:
    name = f"{parent}.initial_view"
    box = subtable(sub, "initial_view", parent)
    view = MapBounds(
        west=_bound(box, "west", 180.0, name),
        south=_bound(box, "south", 90.0, name),
        east=_bound(box, "east", 180.0, name),
        north=_bound(box, "north", 90.0, name),
    )
    if view.west >= view.east or view.south >= view.north:
        raise ValueError(f"{name} must have west < east and south < north")
    return view


def _marker_sizes(sub: dict[str, object], name: str) -> tuple[float, float]:
    """Smallest and largest marker radius in pixels; the largest is never the smaller one."""
    smallest = require_number(sub, "marker_min_px", minimum=0.001, name=name)
    largest = require_number(sub, "marker_max_px", minimum=0.001, name=name)
    if largest < smallest:
        raise ValueError(f"{name}.marker_max_px must be >= {name}.marker_min_px")
    return smallest, largest


def _map(table: dict[str, object]) -> MapDisplay:
    name = f"{_NAME}.map"
    sub = subtable(table, "map", _NAME)
    smallest, largest = _marker_sizes(sub, name)
    tolerance = require_number(sub, "coordinate_tolerance_deg", minimum=0, name=name)
    return MapDisplay(
        light_style=require_str(sub, "light_style", name).strip(),
        dark_style=require_str(sub, "dark_style", name).strip(),
        sector_half_angle_deg=_half_angle(sub, name),
        vertex_spacing_deg=_spacing(sub, name),
        marker_min_px=smallest,
        marker_max_px=largest,
        coordinate_tolerance_deg=tolerance,
        initial_view=_initial_view(sub, name),
    )


def _thresholds(table: dict[str, object]) -> RiskThresholds:
    name = f"{_NAME}.thresholds"
    sub = subtable(table, "thresholds", _NAME)
    values = RiskThresholds(
        hq_concern=require_number(sub, "hq_concern", minimum=0.001, name=name),
        hq_near_lower=require_number(sub, "hq_near_lower", minimum=0, name=name),
        cancer_lower=require_number(sub, "cancer_lower", minimum=0, name=name),
        cancer_upper=require_number(sub, "cancer_upper", minimum=0, name=name),
    )
    if values.hq_near_lower > values.hq_concern:
        raise ValueError(f"{name}.hq_near_lower must not exceed {name}.hq_concern")
    if values.cancer_lower > values.cancer_upper:
        raise ValueError(f"{name}.cancer_lower must not exceed {name}.cancer_upper")
    return values


def _display(table: dict[str, object]) -> Display:
    name = f"{_NAME}.display"
    sub = subtable(table, "display", _NAME)
    return Display(
        significant_digits=require_int(sub, "significant_digits", minimum=1, name=name),
        narrow_breakpoint_px=require_int(sub, "narrow_breakpoint_px", minimum=1, name=name),
        suggestions=names(sub, "suggestions", name, allow_empty=False),
    )


def _share(sub: dict[str, object], key: str, name: str) -> float:
    value = require_number(sub, key, minimum=0, name=name)
    if not 0 < value < 1:
        raise ValueError(f"{name}.{key} must be strictly between 0 and 1")
    return value


def _ordered(name: str, low: float, default: float, high: float) -> None:
    if not low <= default <= high:
        raise ValueError(f"{name} must satisfy min <= default <= max")


def _rail(sub: dict[str, object], parent: str) -> RailLayout:
    name = f"{parent}.rail"
    rail = RailLayout(
        collapsed_px=require_int(sub, "rail_collapsed_px", minimum=1, name=parent),
        default_px=require_int(sub, "rail_default_px", minimum=1, name=parent),
        min_px=require_int(sub, "rail_min_px", minimum=1, name=parent),
        max_px=require_int(sub, "rail_max_px", minimum=1, name=parent),
    )
    _ordered(name, rail.min_px, rail.default_px, rail.max_px)
    if rail.collapsed_px >= rail.min_px:
        raise ValueError(f"{name}: rail_collapsed_px must be below rail_min_px")
    return rail


def _chat(sub: dict[str, object], parent: str) -> ChatLayout:
    chat = ChatLayout(
        default_share=_share(sub, "chat_default_share", parent),
        min_px=require_int(sub, "chat_min_px", minimum=1, name=parent),
        max_share=_share(sub, "chat_max_share", parent),
    )
    if chat.default_share > chat.max_share:
        raise ValueError(f"{parent}.chat_default_share must not exceed chat_max_share")
    return chat


def _overview(sub: dict[str, object], parent: str) -> OverviewLayout:
    overview = OverviewLayout(
        default_share=_share(sub, "overview_default_share", parent),
        min_share=_share(sub, "overview_min_share", parent),
        max_share=_share(sub, "overview_max_share", parent),
    )
    _ordered(f"{parent}.overview", overview.min_share, overview.default_share, overview.max_share)
    return overview


def _layout(table: dict[str, object]) -> Layout:
    name = f"{_NAME}.layout"
    sub = subtable(table, "layout", _NAME)
    return Layout(rail=_rail(sub, name), chat=_chat(sub, name), overview=_overview(sub, name))


def _max_threads(table: dict[str, object]) -> int:
    name = f"{_NAME}.threads"
    return require_int(subtable(table, "threads", _NAME), "max_retained", minimum=1, name=name)


def _priced_on(sub: dict[str, object], name: str) -> date:
    value = sub.get("priced_on")
    if not isinstance(value, date):
        raise ValueError(f"{name}.priced_on must be a TOML date")
    return value


def _price(raw: object, name: str) -> ModelPrice:
    sub = as_table(raw, name)
    return ModelPrice(
        input_usd_per_mtok=require_number(sub, "input_usd_per_mtok", minimum=0, name=name),
        cached_input_usd_per_mtok=require_number(
            sub,
            "cached_input_usd_per_mtok",
            minimum=0,
            name=name,
        ),
        output_usd_per_mtok=require_number(sub, "output_usd_per_mtok", minimum=0, name=name),
        priced_on=_priced_on(sub, name),
        source_url=require_str(sub, "source_url", name).strip(),
    )


def _pricing(table: dict[str, object]) -> Mapping[str, ModelPrice]:
    name = f"{_NAME}.pricing"
    sub = subtable(table, "pricing", _NAME)
    return MappingProxyType({model: _price(raw, f"{name}.{model}") for model, raw in sub.items()})


class _Addresses(TypedDict):
    host: str
    port: int
    container_bind_host: str


def _addresses(table: dict[str, object]) -> _Addresses:
    """The origin's host and port, and the address bound inside a container."""
    return _Addresses(
        host=_loopback_host(table),
        port=_port(table),
        container_bind_host=_container_bind_host(table),
    )


def load_ui_settings(path: Path | None = None) -> UiSettings:
    """Load and validate the web backend and display settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    return UiSettings(
        **_addresses(table),
        frontend_dist=project_path(table, "frontend_dist", _NAME),
        max_key_length=require_int(table, "max_key_length", minimum=1, name=_NAME),
        keyring=_keyring(table),
        prompts=_prompts(table),
        step_labels=_step_labels(table),
        map=_map(table),
        thresholds=_thresholds(table),
        display=_display(table),
        layout=_layout(table),
        max_threads=_max_threads(table),
        pricing=_pricing(table),
        report=parse_report(table),
        exposure_graph=parse_exposure_graph(table),
    )


@lru_cache(maxsize=1)
def get_ui_settings() -> UiSettings:
    """Return the cached UI settings from the default file."""
    return load_ui_settings()
