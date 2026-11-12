"""Chemical property lookup tool."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from commons.cas import format_cas
from commons.units import UnitConversionError, convert
from config.loader import (
    ComptoxSettings,
    MolecularWeightSpec,
    ToxicityValueSpec,
    get_comptox_settings,
    get_unit_settings,
)
from config.pubchem import get_pubchem_settings
from config.user_values import get_user_value_settings
from tools.informatics.helpers.comptox import ComptoxLookup
from tools.informatics.helpers.pubchem import PubchemFallback, PubchemLookup, build_client
from tools.informatics.helpers.pubchem.extract import FieldValue
from tools.informatics.helpers.pubchem.limits import empty_limits
from tools.schemas import (
    ChemicalProperties,
    OccupationalLimits,
    PropertyValue,
    ToxicityDetail,
    ToxicityValue,
)
from tools.user_values import (
    UserValueInputs,
    entry_id,
    missing_entry,
    supplied_value,
    user_value_inputs,
)

# Output fields filled from CompTox; keys must match the configured result keys.
_PROPERTY_FIELDS = ("vapor_pressure", "density")
_TOXICITY_FIELDS = ("rfd", "rfc", "sf", "iur")
# The only fields PubChem may fill: never the name or a toxicity benchmark, whatever it is asked.
_PUBCHEM_FIELDS = ("molecular_weight", *_PROPERTY_FIELDS)
_NO_COMPTOX_DATA = "no CompTox data retrieved (not found or service unavailable)"
_UNRESOLVED = (
    "CAS number {cas!r} could not be resolved in CompTox (not found or service unavailable)"
)
_PUBCHEM = "PubChem"
_NO_NAME = "preferred_name: CompTox gave no name; refer to the chemical by its CAS number"


def _positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


@dataclass
class _Collected:
    """Values, provenance and warnings gathered while building one result."""

    values: dict[str, float | None]
    sources: dict[str, str]
    details: dict[str, ToxicityDetail]
    warnings: list[str]
    name: str | None = None
    limits: OccupationalLimits | None = None

    @classmethod
    def empty(cls) -> _Collected:
        fields = ("molecular_weight", *_PROPERTY_FIELDS, *_TOXICITY_FIELDS)
        return cls(dict.fromkeys(fields), {}, {}, [])

    def add_name(self, name: str | None) -> None:
        """The name CompTox gave, with its source; else a warning (never a name from elsewhere)."""
        self.name = name
        if name is None:
            self.warnings.append(_NO_NAME)
        else:
            self.sources["preferred_name"] = "CompTox"

    def to_properties(self) -> ChemicalProperties:
        v = self.values
        return {
            "preferred_name": self.name,
            "molecular_weight": v["molecular_weight"],
            "vapor_pressure": v["vapor_pressure"],
            "density": v["density"],
            "rfd": v["rfd"],
            "rfc": v["rfc"],
            "sf": v["sf"],
            "iur": v["iur"],
            "sources": self.sources,
            "toxicity_details": self.details,
            "warnings": self.warnings,
            "missing": [],
            "occupational_limits": self.limits or empty_limits("PubChem limits not looked up"),
        }


def _convert_checked(
    out: _Collected,
    field: str,
    value: float,
    unit: str,
    target: str,
    aliases: dict[str, str],
) -> float | None:
    """Convert ``value`` to ``target``; None (with a warning) if it fails or is not positive."""
    try:
        converted = convert(value, unit, target, aliases)
    except UnitConversionError as exc:
        out.warnings.append(f"{field}: {exc}")
        return None
    if not _positive(converted):
        out.warnings.append(
            f"{field}: rejected value {converted!r} {target} (must be a finite number "
            "greater than zero)",
        )
        return None
    return converted


Reported = tuple[float, str, str]  # (value, unit as reported, source)


def _reported(
    record: PropertyValue | ToxicityValue | None,
) -> Reported | None:
    return (record["value"], record["unit"], record["source"]) if record else None


def _add_one(
    out: _Collected,
    field: str,
    reported: Reported | None,
    target: str | None,
    aliases: dict[str, str],
) -> bool:
    """Add one converted value to ``out``; return whether it was added."""
    if target is None:
        out.warnings.append(f"{field}: not configured")
    elif reported is None:
        out.warnings.append(f"{field}: not found in CompTox")
    else:
        value, unit, source = reported
        converted = _convert_checked(out, field, value, unit, target, aliases)
        if converted is not None:
            out.values[field] = converted
            out.sources[field] = source
            return True
    return False


def _add_molecular_weight(
    out: _Collected,
    weight: float | None,
    spec: MolecularWeightSpec,
    aliases: dict[str, str],
) -> None:
    reported = (weight, spec.unit, "CompTox") if weight is not None else None
    _add_one(out, "molecular_weight", reported, spec.target_unit, aliases)


def _add_toxicity(
    out: _Collected,
    field: str,
    record: ToxicityValue | None,
    spec: ToxicityValueSpec | None,
    aliases: dict[str, str],
) -> None:
    target = spec.target_unit if spec else None
    if _add_one(out, field, _reported(record), target, aliases) and record and spec:
        out.details[field] = {
            "source": record["source"],
            "exposure_route": spec.applied_route,
            "route_reported": record["route"],
            "endpoint": record["endpoint"],
            "assessment": record["assessment"],
        }


def _add_comptox_values(
    out: _Collected,
    found: dict[str, PropertyValue],
    toxicity: dict[str, ToxicityValue],
    settings: ComptoxSettings,
    aliases: dict[str, str],
) -> None:
    if not found and not toxicity:
        out.warnings.append(_NO_COMPTOX_DATA)
        return
    targets = {spec.key: spec.target_unit for spec in settings.properties}
    specs = {spec.key: spec for spec in settings.toxicity_values}
    for field in _PROPERTY_FIELDS:
        _add_one(out, field, _reported(found.get(field)), targets.get(field), aliases)
    for field in _TOXICITY_FIELDS:
        _add_toxicity(out, field, toxicity.get(field), specs.get(field), aliases)


def _collect_from_comptox(
    out: _Collected,
    cas: str,
    comptox: ComptoxLookup,
    settings: ComptoxSettings,
    aliases: dict[str, str],
) -> None:
    """Fill ``out`` from CompTox (the primary source) for a valid CAS number."""
    weight = comptox.get_molecular_weight(cas)
    found = comptox.get_properties(cas)
    toxicity = comptox.get_toxicity_values(cas)
    out.warnings.extend(comptox.get_toxicity_notes(cas))
    if weight is None and not found and not toxicity:
        out.warnings.append(_UNRESOLVED.format(cas=cas))
        return
    out.add_name(comptox.get_preferred_name(cas))
    _add_molecular_weight(out, weight, settings.molecular_weight, aliases)
    _add_comptox_values(out, found, toxicity, settings, aliases)


def _fill_from_pubchem(
    out: _Collected,
    key: str,
    candidate: FieldValue,
    aliases: dict[str, str],
) -> None:
    """Add one PubChem value through the same checks as a CompTox value."""
    reported = (candidate.value, candidate.unit, _PUBCHEM)
    if _add_one(out, key, reported, candidate.unit, aliases):
        count = f"median of {candidate.count} statements" if candidate.count > 1 else "1 statement"
        out.warnings.append(f"{key}: CompTox had no value; taken from PubChem ({count})")


def _complete_from_pubchem(
    out: _Collected,
    cas: str,
    pubchem: PubchemFallback,
    aliases: dict[str, str],
) -> None:
    """Ask PubChem for the configured fields still None; never replaces a value."""
    wanted = [key for key in pubchem.fields if key in _PUBCHEM_FIELDS]
    missing = [key for key in wanted if out.values.get(key) is None]
    if not missing:
        return
    offered = pubchem.candidates(cas, missing)
    if offered.problem:
        out.warnings.append(f"PubChem could not help: {offered.problem}")
    for key in missing:
        if key in offered.values:
            _fill_from_pubchem(out, key, offered.values[key], aliases)
        elif key in offered.reasons:
            out.warnings.append(f"{key}: PubChem could not help: {offered.reasons[key]}")


def _add_limits(
    out: _Collected,
    cas: str,
    pubchem: PubchemFallback,
) -> None:
    """Add PubChem's occupational limits (ppm needs the molecular weight found above)."""
    out.limits = pubchem.limits(cas, out.values["molecular_weight"])


def lookup_chemical_properties(
    cas_number: str,
    comptox: ComptoxLookup,
    settings: ComptoxSettings,
    aliases: dict[str, str],
    pubchem: PubchemFallback | None = None,
    inputs: UserValueInputs | None = None,
) -> ChemicalProperties:
    """Collect a chemical's properties from CompTox in the configured target units.

    Every value is checked before it is returned: it must convert to the target unit and be
    a finite number greater than zero; otherwise the field is None with a warning. Fields in
    the PubChem configuration that CompTox left None are then asked of PubChem (when
    ``pubchem`` is given) and pass the same checks; a CompTox value is never replaced.

    Args:
        cas_number: CAS registry number, e.g. "71-43-2".
        comptox: CompTox molecular weight, property and toxicity lookup.
        settings: CompTox settings; supplies each field's target unit.
        aliases: Unit-spelling aliases passed to the converter.
        pubchem: Fallback for the fields CompTox left empty; None means no fallback.
        inputs: The user's answers in this thread (values supplied for missing benchmarks and
            entries declined); None means no answers, so every missing benchmark is listed.

    Returns:
        Every field of ``ChemicalProperties``; None where unavailable, with a warning.

    Raises:
        RuntimeError: If the CAS number is valid and the CompTox API key environment
            variable is not set (raised before any PubChem request).
    """
    out = _Collected.empty()
    cas = format_cas(cas_number)
    if cas is None:
        out.warnings.append(f"CAS number {cas_number!r} is not valid and could not be resolved")
        return out.to_properties()
    _collect_from_comptox(out, cas, comptox, settings, aliases)
    answers = inputs or user_value_inputs(None, get_user_value_settings(), aliases)
    if pubchem is not None:
        _complete_from_pubchem(out, cas, pubchem, aliases)
        _use_supplied_weight(out, cas, answers)  # before the limits: it converts ppm to mg/m^3
        _add_limits(out, cas, pubchem)
    return _with_user_values(out.to_properties(), cas, answers)


def _use_supplied_weight(out: _Collected, cas: str, answers: UserValueInputs) -> None:
    """A molecular weight the user entered, when no source gave one."""
    if out.values["molecular_weight"] is not None:
        return
    key = "molecular_weight"
    value = supplied_value(key, cas, answers.supplied, answers.settings, answers.aliases)
    if value is not None:
        out.values[key] = value
        out.sources[key] = USER_PROVIDED
        out.warnings[:] = [w for w in out.warnings if not w.startswith(f"{key}:")]


# Values asked for when no source has them, with what each is for. A value the user enters is
# theirs: used as given and labelled "user-provided". Only chemistry quantities are asked for.
_ASKED = {
    "rfc": "the inhalation risk: the hazard quotient for this chemical",
    "iur": "the inhalation risk: the cancer risk for this chemical",
    "oel_twa": "the worker screening: comparing workplace air with an 8-hour occupational limit",
    "molecular_weight": "the worker screening: the vapor generation of workplace activities and "
    "converting a limit or measured value in ppm to mg/m3",
    "vapor_pressure": "the worker screening: the vapor generation of workplace activities",
    "density": "the chemical's properties (not used in an equation)",
}
USER_PROVIDED = "user-provided"
_OEL = "oel_twa"


def _limit_is_missing(props: ChemicalProperties) -> bool:
    return props["occupational_limits"]["oel_twa_mg_m3"] is None


def _has(props: ChemicalProperties, quantity: str) -> bool:
    """Whether the chemical already has this value from a source."""
    if quantity == _OEL:
        return not _limit_is_missing(props)
    return props[quantity] is not None  # type: ignore[literal-required]


# `missing` lists the values that are None and that the user may enter, with the accepted units and
# plausible range of each. It is read by the confirmation node, not by the model, so it is not in
# the tool description.
def _with_user_values(
    props: ChemicalProperties,
    cas: str,
    answers: UserValueInputs,
) -> ChemicalProperties:
    """Fill a missing value from the user's answer, or list it as asked for."""
    missing = []
    for quantity, purpose in _ASKED.items():
        if _has(props, quantity):
            continue
        value = supplied_value(quantity, cas, answers.supplied, answers.settings, answers.aliases)
        if value is not None:
            _use_supplied(props, quantity, value)
        elif entry_id(quantity, cas) not in answers.declined:
            missing.append(missing_entry(quantity, cas, purpose, answers.settings))
    props["missing"] = missing
    return props


def _use_supplied(props: ChemicalProperties, quantity: str, value: float) -> None:
    """Set a value the user supplied, labelled as such, and drop its now-false warning."""
    if quantity == _OEL:
        limits = props["occupational_limits"]
        limits["oel_twa_mg_m3"], limits["oel_source"] = value, USER_PROVIDED
        limits["warnings"] = []
    else:
        props[quantity] = value  # type: ignore[literal-required]
    props["sources"][quantity] = USER_PROVIDED
    props["warnings"] = [w for w in props["warnings"] if not w.startswith(f"{quantity}:")]


@dataclass(frozen=True)
class _Services:
    comptox: ComptoxLookup
    settings: ComptoxSettings
    aliases: dict[str, str]
    pubchem: PubchemFallback | None = None


@lru_cache(maxsize=1)
def _services() -> _Services:
    """Build the default collaborators once so the HTTP client and caches are shared."""
    aliases = get_unit_settings().aliases
    pubchem_settings = get_pubchem_settings()
    return _Services(
        comptox=ComptoxLookup(),
        settings=get_comptox_settings(),
        aliases=aliases,
        pubchem=PubchemLookup(build_client(pubchem_settings), pubchem_settings, aliases),
    )


@tool
def fetch_chemical_properties(cas_number: str, config: RunnableConfig) -> ChemicalProperties:
    """Fetch physical-chemical properties and toxicity values for a chemical.

    Purpose:
        Use this to learn what a chemical is and how hazardous it is to breathe or ingest:
        its toxicity benchmarks (`rfc`, `iur`) are what an exposure result is judged
        against, so without them a concentration can be computed but not interpreted. A
        benchmark that comes back null means no usable value exists in the source; the
        matching risk cannot be computed and that must be reported, not replaced by a
        guess. Every value is converted to the fixed unit listed below, so results can be
        used directly (pass `rfc` and `iur` to `calculate_exposure_metrics` as they are).
        `preferred_name` is the only name to call the chemical by; when it is null, refer
        to the chemical by its CAS number alone and never supply a name for it.

    Args:
        cas_number: CAS registry number as the user gave it, e.g. "71-43-2" for benzene
            (hyphens optional). Never a number recalled from a chemical's name: if the user
            gave only a name, ask for the CAS number instead of calling this tool.

    Returns:
        A dict with:
        - preferred_name: the name CompTox calls the chemical by (null when CompTox gave
          none: then the chemical is referred to by its CAS number only)
        - molecular_weight: g/mol (average mass)
        - vapor_pressure: mmHg, as reported by the source (typically at 25 C)
        - density: g/cm^3
        - rfd: oral reference dose, mg/(kg*day) (non-cancer benchmark for ingestion)
        - rfc: inhalation reference concentration, mg/m^3 (non-cancer benchmark)
        - sf: oral cancer slope factor, (mg/(kg*day))^-1
        - iur: inhalation unit risk, (ug/m^3)^-1 (cancer potency)
        - sources: for each value found, "CompTox" (name and molecular weight),
          "experimental" or "predicted" (properties), or the toxicity database name
        - toxicity_details: for each of rfd, rfc, sf and iur that has a value:
          source (database), exposure_route (the route the value applies to: "oral" for
          rfd and sf, "inhalation" for rfc and iur), route_reported (the route as the
          source recorded it, "not specified" if it gave none), endpoint (the critical
          effect or cancer endpoint, e.g. "leukemia"; null if the source gave none) and
          assessment ("cancer" or "non-cancer")
        - warnings: one message per value that is None
        - occupational_limits: workplace exposure limits PubChem lists, in mg/m^3:
          `oel_twa_mg_m3` is the 8-hour time-weighted-average benchmark (OSHA PEL first, then
          NIOSH REL, then ACGIH TLV) with `oel_source`; `limits` holds each limit found
          (TWA, STEL, IDLH, PAC-1/2/3) and `reasons` says why another has no value. They
          are context for worker exposure, never a guess: a null benchmark must be reported.

        When you report a toxicity value, say which exposure route it applies to, its
        source and its endpoint from `toxicity_details`.

        Toxicity values come from the highest-priority database that has them (IRIS
        first). When that database lists several values, the most conservative is
        returned: the lowest RfD or RfC, the highest slope factor or unit risk.

        Any value is None when it was not found, its reported unit could not be
        converted safely, or it was not a positive number; check `warnings` and tell
        the user rather than guessing.
    """
    services = _services()
    settings = get_user_value_settings()
    return lookup_chemical_properties(
        cas_number,
        services.comptox,
        services.settings,
        services.aliases,
        services.pubchem,
        inputs=user_value_inputs(config, settings, services.aliases),
    )
