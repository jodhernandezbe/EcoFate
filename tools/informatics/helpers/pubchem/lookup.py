"""What PubChem can add to a chemical's properties, for one CAS number."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from config.pubchem import PubchemSettings
from tools.informatics.helpers.pubchem.extract import FieldValue, extract_field
from tools.informatics.helpers.pubchem.limits import empty_limits, read_limits
from tools.informatics.helpers.pubchem.record import PugViewRecord
from tools.informatics.helpers.pubchem.resolve import resolve_compound_data
from tools.informatics.helpers.pubchem.transport import JsonGetter
from tools.schemas import OccupationalLimits


@dataclass(frozen=True)
class PubchemCandidates:
    """The values PubChem offers for the fields asked for.

    Attributes:
        values: Field -> value in the field's target unit, for the fields PubChem could give.
        reasons: Field -> why PubChem could not give it, for the other fields asked for.
        problem: Why no record could be used at all (not found, ambiguous, unconfirmed,
            unreachable); None when a record was read.
    """

    values: Mapping[str, FieldValue] = field(default_factory=lambda: {})
    reasons: Mapping[str, str] = field(default_factory=lambda: {})
    problem: str | None = None


class PubchemFallback(Protocol):
    """A second source for the fields CompTox left empty."""

    @property
    def fields(self) -> tuple[str, ...]:
        """The result fields PubChem is asked for (from configuration)."""
        ...

    def candidates(self, cas: str, keys: Sequence[str]) -> PubchemCandidates:
        """Return what PubChem offers for ``keys`` (a subset of ``fields``) of ``cas``."""
        ...

    def limits(self, cas: str, molecular_weight: float | None) -> OccupationalLimits:
        """Return the occupational limits of ``cas`` (mg/m^3); ``molecular_weight`` is g/mol."""
        ...


class PubchemLookup:
    """Looks a CAS number up on PubChem and reads the configured fields; never raises on data."""

    def __init__(
        self,
        client: JsonGetter,
        settings: PubchemSettings,
        aliases: Mapping[str, str],
    ) -> None:
        """Create the lookup.

        Args:
            client: Throttled, retrying, cached JSON client for PubChem.
            settings: PubChem URLs, headings and the fields to read.
            aliases: Unit-spelling aliases for the unit converter.
        """
        self._client = client
        self._settings = settings
        self._aliases = dict(aliases)

    @property
    def fields(self) -> tuple[str, ...]:
        """The result fields PubChem is asked for (from configuration)."""
        return tuple(spec.key for spec in self._settings.fields)

    def candidates(self, cas: str, keys: Sequence[str]) -> PubchemCandidates:
        """Return what PubChem offers for ``keys`` of the chemical with CAS number ``cas``.

        Args:
            cas: Validated, hyphenated CAS number.
            keys: Fields wanted; those not configured are ignored.
        """
        compound = resolve_compound_data(
            cas,
            client=self._client,
            settings=self._settings,
            kind="cas",
        )
        if compound.record is None:
            return PubchemCandidates(problem="; ".join(compound.warnings))
        return self._read_fields(compound.record, keys)

    def limits(self, cas: str, molecular_weight: float | None) -> OccupationalLimits:
        """Return the occupational limits of the chemical with CAS number ``cas``.

        Uses the same cached PUG View response as ``candidates``; never raises on data.

        Args:
            cas: Validated, hyphenated CAS number.
            molecular_weight: Molecular weight, g/mol, for limits given in ppm; None if unknown.
        """
        compound = resolve_compound_data(
            cas,
            client=self._client,
            settings=self._settings,
            kind="cas",
        )
        if compound.record is None:
            return empty_limits("PubChem limits unavailable: " + "; ".join(compound.warnings))
        return read_limits(
            compound.record,
            molecular_weight,
            self._settings.limits,
            self._settings.agreement_ratio,
        )

    def _read_fields(self, record: PugViewRecord, keys: Sequence[str]) -> PubchemCandidates:
        values: dict[str, FieldValue] = {}
        reasons: dict[str, str] = {}
        ratio = self._settings.agreement_ratio
        for spec in (s for s in self._settings.fields if s.key in keys):
            found = extract_field(record, spec, ratio, self._aliases)
            if found.value is not None:
                values[spec.key] = found.value
            else:
                reasons[spec.key] = found.reason or "no value"
        return PubchemCandidates(values, reasons)
