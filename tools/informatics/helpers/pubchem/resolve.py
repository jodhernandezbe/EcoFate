"""From a CAS number, SMILES or name to a confirmed PubChem compound record."""

from __future__ import annotations

from dataclasses import dataclass

from config.pubchem import PubchemSettings
from tools.informatics.helpers.pubchem.client import (
    fetch_pubchem_pug_view_json,
    get_cid_by_identifier,
)
from tools.informatics.helpers.pubchem.identifiers import IdentifierKind, prepare_identifier
from tools.informatics.helpers.pubchem.record import PugViewRecord, confirms_cas
from tools.informatics.helpers.pubchem.transport import JsonGetter


@dataclass(frozen=True)
class Compound:
    """What resolving an identifier found.

    Attributes:
        kind: How the identifier was read: ``"cas"``, ``"smiles"`` or ``"name"``.
        query: What PubChem was searched with (hyphenated CAS, canonical SMILES or name).
        cid: PubChem compound ID, or None if none was found.
        record: The PUG View record, or None if there is none or it was not confirmed.
        warnings: Why a step failed, if one did.
    """

    kind: IdentifierKind
    query: str
    cid: int | None
    record: PugViewRecord | None
    warnings: tuple[str, ...]


def _unconfirmed(cas: str) -> str:
    return f"PubChem's record does not list CAS number {cas}; the match was not confirmed"


def resolve_compound_data(
    identifier: str,
    *,
    client: JsonGetter,
    settings: PubchemSettings,
    kind: IdentifierKind | None = None,
) -> Compound:
    """Resolve a CAS number, SMILES or name to its PubChem CID and record.

    A SMILES is validated and canonicalized with RDKit first. A record found for a CAS number
    is kept only if it lists that CAS number itself (a name search can match another chemical).
    A failed step stops the chain and its reason goes into ``warnings``; data problems do not
    raise.

    Args:
        identifier: A CAS number, a SMILES or a chemical name.
        client: Throttled, retrying, cached JSON client for PubChem.
        settings: PubChem URLs and headings.
        kind: Skip detection and read ``identifier`` as this kind.

    Raises:
        ValueError: If ``identifier`` is blank, or is stated to be a SMILES that RDKit cannot
            parse or a CAS number that is not valid.
    """
    prepared = prepare_identifier(identifier, kind)
    cid = get_cid_by_identifier(prepared.query, prepared.kind, client=client, settings=settings)
    if cid.value is None:
        return Compound(prepared.kind, prepared.query, None, None, (cid.reason or "",))
    record = fetch_pubchem_pug_view_json(cid.value, client=client, settings=settings)
    if record.value is None:
        return Compound(prepared.kind, prepared.query, cid.value, None, (record.reason or "",))
    if prepared.kind == "cas" and not confirms_cas(
        record.value,
        prepared.query,
        settings.cas_heading,
    ):
        warnings = (_unconfirmed(prepared.query),)
        return Compound(prepared.kind, prepared.query, cid.value, None, warnings)
    return Compound(prepared.kind, prepared.query, cid.value, record.value, ())
