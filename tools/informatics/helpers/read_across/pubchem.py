"""CAS number -> SMILES and molecular weight from PubChem PUG REST (looked up by name)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

from config.read_across import PubchemSettings
from tools.http import HttpRequestError, RetryingClient

_NOT_FOUND = 404


@dataclass(frozen=True)
class PubchemCompound:
    """What PubChem reports for one compound.

    Attributes:
        smiles: SMILES as reported (not yet canonicalized).
        molecular_weight: Molecular weight in g/mol, or None if PubChem gave no usable one.
    """

    smiles: str
    molecular_weight: float | None


def _weight(value: object) -> float | None:
    """Return a finite, positive weight from a number or numeric string; never a bool."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def _smiles(entry: dict[str, object], settings: PubchemSettings) -> str | None:
    for key in settings.smiles_properties:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _entries(payload: object) -> list[dict[str, object]]:
    """Return the property entries of a PUG REST answer; empty if the shape is unexpected."""
    body = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
    table = body.get("PropertyTable")
    rows = cast(dict[str, object], table).get("Properties") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return []
    items = cast(list[object], rows)
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def _compound(payload: object, settings: PubchemSettings) -> PubchemCompound | str:
    entries = _entries(payload)
    found = [(s, entry) for entry in entries if (s := _smiles(entry, settings)) is not None]
    if not found:
        return "PubChem returned no SMILES"
    if len({smiles for smiles, _ in found}) > 1:
        return "PubChem matched several different compounds; the structure is ambiguous"
    smiles, entry = found[0]
    return PubchemCompound(smiles, _weight(entry.get(settings.weight_property)))


def fetch_compound(
    cas: str,
    client: RetryingClient,
    settings: PubchemSettings,
) -> PubchemCompound | str:
    """Look up a chemical's SMILES and molecular weight on PubChem.

    Args:
        cas: Validated, hyphenated CAS number.
        client: Retrying JSON client using the PubChem request policy.
        settings: PubChem URL template and response property names.

    Returns:
        The compound, or a reason (str) why none could be read: not found, service
        unavailable, malformed answer, or several different compounds for one CAS number.
    """
    try:
        payload = client.get_json(settings.url(cas))
    except HttpRequestError as exc:
        if exc.status_code == _NOT_FOUND:
            return f"PubChem has no compound for CAS number {cas}"
        return f"PubChem could not be reached ({exc})"
    return _compound(payload, settings)
