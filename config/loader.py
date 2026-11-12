"""Typed loader for ``config/settings.toml``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from config.iris import IrisSettings, parse_iris
from config.parsing import DEFAULT_SETTINGS_PATH as DEFAULT_SETTINGS_PATH
from config.parsing import names as _names
from config.parsing import read_toml as _read_toml
from config.parsing import require_bool as _require_bool
from config.parsing import require_int as _require_int
from config.parsing import require_number as _require_number
from config.parsing import require_str as _require_str
from config.parsing import section as _section


@dataclass(frozen=True)
class PropertySpec:
    """One CompTox property to extract.

    Attributes:
        key: Key used in the lookup result, e.g. ``"vapor_pressure"``.
        name: CompTox ``propName`` to match exactly, e.g. ``"Vapor Pressure"``.
        target_unit: Unit the value is converted to, e.g. ``"mmHg"``.
    """

    key: str
    name: str
    target_unit: str


@dataclass(frozen=True)
class MolecularWeightSpec:
    """Where CompTox reports molecular weight and in which units.

    Attributes:
        field: Field of the chemical detail response that holds it, e.g. ``"averageMass"``.
        unit: Unit the API reports it in (the response carries none), e.g. ``"g/mol"``.
        target_unit: Unit the value is converted to, e.g. ``"g/mol"``.
    """

    field: str
    unit: str
    target_unit: str


@dataclass(frozen=True)
class ToxicityValueSpec:
    """One CompTox ToxVal toxicity value to extract.

    Attributes:
        key: Key used in the lookup result, e.g. ``"rfd"``.
        types: Accepted ``toxvalType`` labels (exact match), e.g. ``("RfC",)``.
        routes: Accepted ``exposureRoute`` values, lower-case, e.g. ``("inhalation",)``. The
            first is the route the value applies to (reported to the user as the applied route).
        prefer: ``"lowest"`` or ``"highest"``: which value to take among the records of the
            best-ranked source (the most conservative one).
        target_unit: Unit the value is converted to, e.g. ``"mg/m^3"``.
    """

    key: str
    types: tuple[str, ...]
    routes: tuple[str, ...]
    prefer: Literal["lowest", "highest"]
    target_unit: str

    @property
    def applied_route(self) -> str:
        """Route the value applies to: the first accepted route."""
        return self.routes[0]


@dataclass(frozen=True)
class UnitSettings:
    """Unit-conversion settings.

    Attributes:
        aliases: Source unit spelling -> Pint-parsable unit string.
    """

    aliases: dict[str, str]


@dataclass(frozen=True)
class ComptoxSettings:
    """EPA CompTox Chemicals Dashboard API settings.

    The API key itself is never stored here; only the environment variable that holds it.

    Attributes:
        base_url: Service root URL, without trailing slash.
        dtxsid_by_cas_path: Path template appended to ``base_url``; contains ``{casrn}``.
        detail_by_dtxsid_path: Path template appended to ``base_url``; contains ``{dtxsid}``.
        properties_by_dtxsid_path: Path template appended to ``base_url``; contains ``{dtxsid}``.
        toxval_by_dtxsid_path: Path template appended to ``base_url``; contains ``{dtxsid}``.
        source_priority: ToxVal ``source`` names, most preferred first.
        api_key_header: Name of the HTTP header carrying the API key.
        api_key_env_var: Name of the environment variable holding the API key.
        delay_seconds: Wait before each request, in seconds.
        timeout_seconds: Per-request timeout, in seconds.
        max_retries: Retries after a timeout, a connection error, HTTP 429 or HTTP 5xx.
        backoff_seconds: First retry wait in seconds; doubles on each further retry.
        accept_expired_certificate: Skip only the validity-dates check of the service's TLS
            certificate (its chain and host name are still verified); for an outage where
            the certificate has lapsed. Off unless set, and to be turned off again after.
        molecular_weight: Where molecular weight is read from and its units.
        properties: Properties to extract, in order.
        toxicity_values: Toxicity values to extract, in order.
        iris: The CompTox IRIS endpoint read ahead of ToxVal; None leaves it unused.
    """

    base_url: str
    dtxsid_by_cas_path: str
    detail_by_dtxsid_path: str
    properties_by_dtxsid_path: str
    toxval_by_dtxsid_path: str
    source_priority: tuple[str, ...]
    api_key_header: str
    api_key_env_var: str
    delay_seconds: float
    timeout_seconds: float
    max_retries: int
    backoff_seconds: float
    accept_expired_certificate: bool
    molecular_weight: MolecularWeightSpec
    properties: tuple[PropertySpec, ...]
    toxicity_values: tuple[ToxicityValueSpec, ...]
    iris: IrisSettings | None = None

    @property
    def dtxsid_by_cas_url(self) -> str:
        """Full URL template containing the ``{casrn}`` placeholder."""
        return self.base_url.rstrip("/") + self.dtxsid_by_cas_path

    @property
    def detail_by_dtxsid_url(self) -> str:
        """Full URL template containing the ``{dtxsid}`` placeholder."""
        return self.base_url.rstrip("/") + self.detail_by_dtxsid_path

    @property
    def properties_by_dtxsid_url(self) -> str:
        """Full URL template containing the ``{dtxsid}`` placeholder."""
        return self.base_url.rstrip("/") + self.properties_by_dtxsid_path

    @property
    def toxval_by_dtxsid_url(self) -> str:
        """Full URL template containing the ``{dtxsid}`` placeholder."""
        return self.base_url.rstrip("/") + self.toxval_by_dtxsid_path

    @property
    def iris_by_dtxsid_url(self) -> str | None:
        """Full IRIS-endpoint URL template with ``{dtxsid}``; None when it is not configured."""
        return self.base_url.rstrip("/") + self.iris.path if self.iris else None


TRI_FIELD_KEYS = (
    "medium",
    "year",
    "doc_ctrl_num",
    "quantity",
    "unit",
    "facility_name",
    "latitude",
    "longitude",
    "address",
    "city",
    "county",
    "state",
    "zip_code",
    "naics_code",
    "naics_primary",
)
_MAX_HOURS_PER_YEAR = 8784  # 366 days x 24 h


@dataclass(frozen=True)
class TriSettings:
    """EPA Envirofacts TRI release-query settings.

    Attributes:
        release_path: Path template appended to the Envirofacts base URL; contains ``{casrn}``,
            ``{medium}``, ``{after_year}``, ``{start}`` and ``{end}`` (inclusive row range).
        media: Environmental media to keep, e.g. ``("AIR STACK",)``; one query per medium.
        fugitive_medium: The medium of fugitive air releases, read in one more query per chemical;
            its release is put on the records of ``media``; a facility with only that release is
            worker-only.
        page_size: Rows requested per page.
        max_pages: Most pages fetched per medium.
        recent_years: Reporting years that count, ending with the newest that can be published.
        publication_lag_years: Years TRI lags the calendar (year N is released in N + 1).
        max_listed: Most facilities the inventory tool lists to the model, largest rate first.
        max_worker_only: Most fugitive-only (worker-only) facilities kept, largest release first.
        east_longitude_states: State codes whose longitudes are east of Greenwich.
        facility_id_fields: TRI columns holding the FRS ID, first one set wins.
        fields: Result key (see ``TRI_FIELD_KEYS``) -> TRI column name.
    """

    release_path: str
    media: tuple[str, ...]
    fugitive_medium: str
    page_size: int
    max_pages: int
    recent_years: int
    publication_lag_years: int
    max_listed: int
    max_worker_only: int
    east_longitude_states: tuple[str, ...]
    facility_id_fields: tuple[str, ...]
    fields: Mapping[str, str]

    def after_year(self, current_year: int) -> int:
        """Return the year after which reports count (the window starts the year after it)."""
        return current_year - self.publication_lag_years - self.recent_years

    def first_year(self, current_year: int) -> int:
        """Return the first reporting year inside the window."""
        return self.after_year(current_year) + 1


@dataclass(frozen=True)
class EmissionsSettings:
    """Assumptions used to turn reported releases into emission rates.

    Attributes:
        operating_hours_per_year: Hours per year a source is assumed to operate (8760 is
            continuous operation).
    """

    operating_hours_per_year: float


def _tables(section: dict[str, object], key: str) -> list[dict[str, object]]:
    """Return the non-empty array of tables ``comptox.<key>`` as plain dicts."""
    raw = section.get(key)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"comptox.{key} must be a non-empty list")
    tables: list[dict[str, object]] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ValueError(f"comptox.{key} entries must be tables")
        tables.append({str(k): v for k, v in cast(dict[object, object], item).items()})
    return tables


def _require_unique(keys: list[str], where: str) -> None:
    if len(set(keys)) != len(keys):
        raise ValueError(f"{where} keys must be unique")


def _property_spec(entry: dict[str, object]) -> PropertySpec:
    where = "comptox.properties"
    return PropertySpec(
        key=_require_str(entry, "key", where),
        name=_require_str(entry, "name", where),
        target_unit=_require_str(entry, "target_unit", where),
    )


def _parse_properties(section: dict[str, object]) -> tuple[PropertySpec, ...]:
    specs = tuple(_property_spec(entry) for entry in _tables(section, "properties"))
    _require_unique([spec.key for spec in specs], "comptox.properties")
    return specs


def _parse_source_priority(section: dict[str, object]) -> tuple[str, ...]:
    raw = section.get("source_priority", [])
    if not isinstance(raw, list):
        raise ValueError("comptox.source_priority must be a list of strings")
    names = cast(list[object], raw)
    if not all(isinstance(n, str) and n.strip() for n in names):
        raise ValueError("comptox.source_priority must be a list of non-empty strings")
    return tuple(cast(list[str], names))


def _parse_molecular_weight(section: dict[str, object]) -> MolecularWeightSpec:
    raw = section.get("molecular_weight")
    if not isinstance(raw, dict):
        raise ValueError("comptox.molecular_weight must be a table")
    entry = {str(k): v for k, v in cast(dict[object, object], raw).items()}
    name = "comptox.molecular_weight"
    return MolecularWeightSpec(
        field=_require_str(entry, "field", name),
        unit=_require_str(entry, "unit", name),
        target_unit=_require_str(entry, "target_unit", name),
    )


def _string_list(entry: dict[str, object], key: str) -> tuple[str, ...]:
    value = entry.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(v, str) and v.strip() for v in cast(list[object], value))
    ):
        raise ValueError(f"comptox.toxicity_values.{key} must be a non-empty list of strings")
    return tuple(cast(list[str], value))


def _toxicity_spec(entry: dict[str, object]) -> ToxicityValueSpec:
    where = "comptox.toxicity_values"
    prefer = entry.get("prefer")
    if prefer not in ("lowest", "highest"):
        raise ValueError(f"{where}.prefer must be 'lowest' or 'highest'")
    return ToxicityValueSpec(
        key=_require_str(entry, "key", where),
        types=_string_list(entry, "types"),
        routes=tuple(route.strip().lower() for route in _string_list(entry, "routes")),
        prefer=prefer,
        target_unit=_require_str(entry, "target_unit", where),
    )


def _parse_toxicity_values(section: dict[str, object]) -> tuple[ToxicityValueSpec, ...]:
    specs = tuple(_toxicity_spec(entry) for entry in _tables(section, "toxicity_values"))
    _require_unique([spec.key for spec in specs], "comptox.toxicity_values")
    return specs


def _parse_iris(section: dict[str, object]) -> IrisSettings | None:
    keys = tuple(spec.key for spec in _parse_toxicity_values(section))
    return parse_iris(section, keys)


def _require_template(section: dict[str, object], key: str, placeholder: str) -> str:
    template = _require_str(section, key, "comptox")
    if placeholder not in template:
        raise ValueError(f"comptox.{key} must contain {placeholder}")
    return template


def _comptox_str(section: dict[str, object], key: str) -> str:
    return _require_str(section, key, "comptox")


def _comptox_seconds(section: dict[str, object], key: str, minimum: float) -> float:
    return _require_number(section, key, minimum=minimum, name="comptox")


def _comptox_paths(section: dict[str, object]) -> dict[str, str]:
    """The request path templates, each checked for its placeholder."""
    return {
        "dtxsid_by_cas_path": _require_template(section, "dtxsid_by_cas_path", "{casrn}"),
        "detail_by_dtxsid_path": _require_template(section, "detail_by_dtxsid_path", "{dtxsid}"),
        "properties_by_dtxsid_path": _require_template(
            section,
            "properties_by_dtxsid_path",
            "{dtxsid}",
        ),
        "toxval_by_dtxsid_path": _require_template(section, "toxval_by_dtxsid_path", "{dtxsid}"),
    }


def load_comptox_settings(path: Path | None = None) -> ComptoxSettings:
    """Load and validate CompTox settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (delay and timeout in seconds).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    section = _section(_read_toml(path), "comptox")
    return ComptoxSettings(
        base_url=_comptox_str(section, "base_url"),
        **_comptox_paths(section),
        source_priority=_parse_source_priority(section),
        api_key_header=_comptox_str(section, "api_key_header"),
        api_key_env_var=_comptox_str(section, "api_key_env_var"),
        delay_seconds=_comptox_seconds(section, "delay_seconds", 0),
        timeout_seconds=_comptox_seconds(section, "timeout_seconds", 0.001),
        max_retries=_require_int(section, "max_retries", minimum=0, name="comptox"),
        backoff_seconds=_comptox_seconds(section, "backoff_seconds", 0),
        accept_expired_certificate=_require_bool(section, "accept_expired_certificate", "comptox"),
        molecular_weight=_parse_molecular_weight(section),
        properties=_parse_properties(section),
        toxicity_values=_parse_toxicity_values(section),
        iris=_parse_iris(section),
    )


@lru_cache(maxsize=1)
def get_comptox_settings() -> ComptoxSettings:
    """Return the cached CompTox settings from the default file."""
    return load_comptox_settings()


def load_unit_settings(path: Path | None = None) -> UnitSettings:
    """Load and validate unit-conversion settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The alias table; empty if the file has no ``[units.aliases]`` table.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the alias table is not a table of non-empty strings.
    """
    data = _read_toml(path)
    units = data.get("units")
    if units is None:
        return UnitSettings(aliases={})
    if not isinstance(units, dict):
        raise ValueError("units must be a table")
    raw = cast(dict[str, object], units).get("aliases", {})
    if not isinstance(raw, dict):
        raise ValueError("units.aliases must be a table")
    aliases: dict[str, str] = {}
    for source, target in cast(dict[object, object], raw).items():
        if not isinstance(source, str) or not source.strip():
            raise ValueError("units.aliases keys must be non-empty strings")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"units.aliases.{source} must be a non-empty string")
        aliases[source.strip()] = target.strip()
    return UnitSettings(aliases=aliases)


@lru_cache(maxsize=1)
def get_unit_settings() -> UnitSettings:
    """Return the cached unit settings from the default file."""
    return load_unit_settings()


def _parse_tri_fields(section: dict[str, object]) -> Mapping[str, str]:
    raw = section.get("fields")
    if not isinstance(raw, dict):
        raise ValueError("tri.fields must be a table")
    table = {str(k): v for k, v in cast(dict[object, object], raw).items()}
    return MappingProxyType({key: _require_str(table, key, "tri.fields") for key in TRI_FIELD_KEYS})


def _tri_template(section: dict[str, object]) -> str:
    template = _require_str(section, "release_path", "tri")
    for slot in ("{casrn}", "{medium}", "{after_year}", "{start}", "{end}"):
        if slot not in template:
            raise ValueError(f"tri.release_path must contain {slot}")
    return template


def _fugitive_medium(section: dict[str, object]) -> str:
    medium = _require_str(section, "fugitive_medium", "tri").strip()
    if medium in _names(section, "media", "tri", allow_empty=False):
        raise ValueError("tri.fugitive_medium must not also be listed in tri.media")
    return medium


def load_tri_settings(path: Path | None = None) -> TriSettings:
    """Load and validate TRI release-query settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings .

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    section = _section(_read_toml(path), "tri")
    return TriSettings(
        release_path=_tri_template(section),
        media=_names(section, "media", "tri", allow_empty=False),
        fugitive_medium=_fugitive_medium(section),
        page_size=_require_int(section, "page_size", minimum=1, name="tri"),
        max_pages=_require_int(section, "max_pages", minimum=1, name="tri"),
        recent_years=_require_int(section, "recent_years", minimum=1, name="tri"),
        publication_lag_years=_require_int(section, "publication_lag_years", minimum=0, name="tri"),
        max_listed=_require_int(section, "max_listed", minimum=1, name="tri"),
        max_worker_only=_require_int(section, "max_worker_only", minimum=1, name="tri"),
        east_longitude_states=_names(section, "east_longitude_states", "tri", allow_empty=True),
        facility_id_fields=_names(section, "facility_id_fields", "tri", allow_empty=False),
        fields=_parse_tri_fields(section),
    )


@lru_cache(maxsize=1)
def get_tri_settings() -> TriSettings:
    """Return the cached TRI settings from the default file."""
    return load_tri_settings()


def load_emissions_settings(path: Path | None = None) -> EmissionsSettings:
    """Load and validate emission-rate assumptions.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid, including operating hours that are not
            in (0, 8784] hours per year; the message names the key.
    """
    section = _section(_read_toml(path), "emissions")
    hours = _require_number(section, "operating_hours_per_year", minimum=0, name="emissions")
    if not 0 < hours <= _MAX_HOURS_PER_YEAR:
        raise ValueError(
            f"emissions.operating_hours_per_year must be > 0 and <= {_MAX_HOURS_PER_YEAR}",
        )
    return EmissionsSettings(operating_hours_per_year=hours)


@lru_cache(maxsize=1)
def get_emissions_settings() -> EmissionsSettings:
    """Return the cached emissions settings from the default file."""
    return load_emissions_settings()
