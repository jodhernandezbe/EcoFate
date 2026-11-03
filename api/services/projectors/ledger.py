"""The ledger: validated tool results collected from a thread, in the order they happened."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from api.schemas.workspace import Screening
from api.services.projectors.payloads import (
    EmissionPayload,
    ExposurePayload,
    IndustryPayload,
    MeteorologyPayload,
    OccupationalPayload,
    PopulationPayload,
    ProfilePayload,
    PropertiesPayload,
    ReadAcrossPayload,
    SccMatchPayload,
    StackPayload,
    WorstCaseScenarioPayload,
    decode_json,
    validate,
)


@dataclass(frozen=True)
class ToolExchange:
    """One tool call with its result: the arguments, the text the model got and any artifact.

    An artifact is what a tool returned beside that text for the program only (the model never
    sees it), such as the complete inventory when the model is told only the largest facilities.
    """

    name: str
    args: Mapping[str, object]
    content: object
    artifact: object = None


@dataclass(frozen=True)
class Located[P]:
    """A result for a point (decimal degrees), as the tool call named it."""

    latitude: float
    longitude: float
    payload: P


@dataclass(frozen=True)
class Receptor:
    """A population result with the radius (km) it was computed for."""

    point: Located[PopulationPayload]
    radius_km: float


@dataclass
class Ledger:
    """Everything the workspace is built from. Projectors fill it; nothing here is derived."""

    default_radius_km: float
    cas: str | None = None
    facilities: dict[str, EmissionPayload] = field(default_factory=dict[str, EmissionPayload])
    facility_cas: dict[str, str] = field(default_factory=dict[str, str])
    industries: list[tuple[str, IndustryPayload]] = field(
        default_factory=list[tuple[str, IndustryPayload]],
    )
    nei: list[tuple[str, list[StackPayload]]] = field(
        default_factory=list[tuple[str, list[StackPayload]]],
    )
    scc_stacks: list[StackPayload] = field(default_factory=list[StackPayload])
    scc_matches: dict[str, SccMatchPayload] = field(default_factory=dict[str, SccMatchPayload])
    properties: tuple[str, PropertiesPayload] | None = None
    read_across: tuple[str, ReadAcrossPayload] | None = None
    meteorology: list[Located[MeteorologyPayload]] = field(
        default_factory=list[Located[MeteorologyPayload]],
    )
    population: list[Receptor] = field(default_factory=list[Receptor])
    # Keyed by the emission rate the model passed, or by FRS ID (batch assessment).
    exposures: list[tuple[float | str, ExposurePayload]] = field(
        default_factory=list[tuple[float | str, ExposurePayload]],
    )
    # FRS ID -> the worker screening and the operational profile of the batch assessment.
    worker: dict[str, OccupationalPayload] = field(default_factory=dict[str, OccupationalPayload])
    profiles: dict[str, ProfilePayload] = field(default_factory=dict[str, ProfilePayload])
    # FRS ID -> the worst-case scenarios of the batch assessment.
    scenarios: dict[str, list[WorstCaseScenarioPayload]] = field(
        default_factory=dict[str, list[WorstCaseScenarioPayload]],
    )
    # FRS ID -> how the batch assessment screened that facility.
    screening: dict[str, Screening] = field(default_factory=dict[str, Screening])
    warnings: list[str] = field(default_factory=list[str])

    def read[T](self, exchange: ToolExchange, model: type[T]) -> T | None:
        """The result as ``model``; None (and a warning) when it is not JSON of that shape."""
        value = validate(model, decode_json(exchange.content))
        if value is None:
            self.skip(exchange, "its result was not valid")
        return value

    def skip(self, exchange: ToolExchange, why: str) -> None:
        """Record that a result was left out of the workspace."""
        self.warnings.append(f"Left out a {exchange.name} result: {why}.")

    def note_cas(self, exchange: ToolExchange) -> None:
        """Remember the CAS number the model asked about (the latest one is the chemical)."""
        cas = exchange.args.get("cas_number")
        if isinstance(cas, str) and cas.strip():
            self.cas = cas.strip()


def number(args: Mapping[str, object], key: str) -> float | None:
    """A finite number argument; None for anything else (a ``bool`` is not a number)."""
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def text(args: Mapping[str, object], key: str) -> str | None:
    """A text or integer identifier argument as text (``str`` of an int); None otherwise."""
    value = args.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None
