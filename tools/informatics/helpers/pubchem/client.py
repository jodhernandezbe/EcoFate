"""PubChem lookups: the CID of a compound and its PUG View record."""

from __future__ import annotations

from typing import Literal, cast

from config.pubchem import PubchemSettings
from tools.http import HttpRequestError
from tools.informatics.helpers.pubchem.identifiers import canonical_smiles
from tools.informatics.helpers.pubchem.record import PugViewRecord, has_record
from tools.informatics.helpers.pubchem.result import Lookup
from tools.informatics.helpers.pubchem.transport import JsonGetter

SearchType = Literal["smiles", "cas", "name"]
_NOT_FOUND = 404


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _cids(payload: object) -> list[object] | None:
    """The CID list of a PUG REST answer, or None if the answer has another shape."""
    body = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
    listing = body.get("IdentifierList")
    cids = cast(dict[str, object], listing).get("CID") if isinstance(listing, dict) else None
    return cast(list[object], cids) if isinstance(cids, list) else None


def _one_cid(payload: object, what: str) -> Lookup[int]:
    cids = _cids(payload)
    if not cids or not all(_positive_int(cid) for cid in cids):
        return Lookup[int].missing("PubChem's answer was not understood (no valid compound ID)")
    distinct = {cast(int, cid) for cid in cids}
    if len(distinct) > 1:
        return Lookup[int].missing(
            f"PubChem matched {len(distinct)} compounds for {what}: ambiguous",
        )
    return Lookup[int].found(distinct.pop())


def _failure(exc: HttpRequestError, what: str) -> str:
    if exc.status_code == _NOT_FOUND:
        return f"PubChem has no compound for {what}"
    return f"PubChem could not be reached ({exc})"


def get_cid_by_identifier(
    query: str,
    search_type: SearchType = "smiles",
    *,
    client: JsonGetter,
    settings: PubchemSettings,
) -> Lookup[int]:
    """Find the PubChem compound ID (CID) of a SMILES, CAS number or name.

    Args:
        query: The SMILES, the hyphenated CAS number or the chemical name.
        search_type: What ``query`` is; a CAS number is searched as a name.
        client: Throttled, retrying, cached JSON client for PubChem.
        settings: PubChem URL templates.

    Returns:
        The CID, or the reason there is none: not found, several different compounds
        (ambiguous, none is picked), an answer that was not understood, or PubChem unreachable.

    Raises:
        ValueError: If ``search_type`` is unknown, or ``query`` is a SMILES RDKit cannot parse.
    """
    if search_type == "smiles":
        smiles = canonical_smiles(query)
        url = settings.smiles_url(smiles)
    elif search_type in ("cas", "name"):
        url = settings.name_url(query.strip())
    else:
        raise ValueError(f"unknown search type {search_type!r}")
    what = f"{search_type} {query.strip()!r}"
    try:
        payload = client.get_json(url)
    except HttpRequestError as exc:
        return Lookup[int].missing(_failure(exc, what))
    return _one_cid(payload, what)


def fetch_pubchem_pug_view_json(
    cid: int,
    *,
    client: JsonGetter,
    settings: PubchemSettings,
) -> Lookup[PugViewRecord]:
    """Fetch the PUG View record of a compound.

    Args:
        cid: PubChem compound ID, a positive integer.
        client: Throttled, retrying, cached JSON client for PubChem.
        settings: PubChem URL templates.

    Returns:
        The decoded JSON record, or the reason there is none.

    Raises:
        ValueError: If ``cid`` is not a positive integer.
    """
    if not _positive_int(cid):
        raise ValueError(f"CID must be a positive integer, got {cid!r}")
    try:
        payload = client.get_json(settings.record_url(cid))
    except HttpRequestError as exc:
        return Lookup[PugViewRecord].missing(_failure(exc, f"CID {cid}"))
    if not has_record(payload):
        return Lookup[PugViewRecord].missing(f"PubChem's record for CID {cid} was not understood")
    return Lookup[PugViewRecord].found(cast(PugViewRecord, payload))
