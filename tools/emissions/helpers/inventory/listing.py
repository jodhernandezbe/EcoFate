"""What the model is told about an inventory: filtered, ranked and capped."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from tools.schemas import EmissionRecord, FacilityRecord, InventoryResult, WorkerOnlyFacility


def _matches(record: FacilityRecord, state: str | None, city: str | None) -> bool:
    if state is not None and (record["state"] or "").strip().upper() != state:
        return False
    return city is None or (record["city"] or "").strip().upper() == city


def _clean(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    return text or None


def _note(matching: int, shown: int, filtered: bool) -> str | None:
    if matching == 0:
        return "No facility matches the filters." if filtered else None
    if matching <= shown:
        return None
    return (
        f"Only the {shown} facilities with the highest emission rates of the {matching} that "
        "match are listed; the others are not shown and the list must not be treated as "
        "complete. Give `state` or `city` to see the largest in one place."
    )


def _view(
    found: int,
    matching: list[EmissionRecord],
    listed: list[EmissionRecord],
    filtered: bool,
) -> InventoryResult:
    """The stack view; the fugitive-only facilities are added apart (``with_worker_only``)."""
    return {
        "total_found": found,
        "matching": len(matching),
        "shown": len(listed),
        "facilities": listed,
        "note": _note(len(matching), len(listed), filtered),
        "worker_only": [],
        "worker_only_left_out": 0,
    }


def rank_and_cap(
    records: Sequence[EmissionRecord],
    max_listed: int,
    state: str | None = None,
    city: str | None = None,
    enrich: Callable[[list[EmissionRecord]], list[EmissionRecord]] | None = None,
) -> tuple[InventoryResult, list[EmissionRecord]]:
    """Rank facilities by emission rate and cap what the model sees.

    Args:
        records: Every facility found for the chemical.
        max_listed: Most facilities listed to the model.
        state: Keep only facilities in this state (postal abbreviation, any case).
        city: Keep only facilities in this city (any case, exact name).
        enrich: Applied to the listed facilities only (lookups worth making for the few the
            model sees, not for every facility found); returns them in the same order.

    Returns:
        The model's view (``InventoryResult``) and the complete matching list, largest
        emission rate first, for the interface.
    """
    wanted_state, wanted_city = _clean(state), _clean(city)
    matching = sorted(
        (r for r in records if _matches(r, wanted_state, wanted_city)),
        key=lambda r: r["emission_rate"],
        reverse=True,
    )
    listed = enrich(matching[:max_listed]) if enrich else matching[:max_listed]
    matching[: len(listed)] = listed
    filtered = wanted_state is not None or wanted_city is not None
    return _view(len(records), matching, listed, filtered), matching


def _by_release(facility: WorkerOnlyFacility) -> float:
    """The sort key: the fugitive release in kg/yr, a facility without one last."""
    release = facility["fugitive_release_kg_per_year"]
    return release if release is not None else -1.0


def _with_cap_note(note: str | None, cap: int, left_out: int) -> str | None:
    if not left_out:
        return note
    extra = (
        f"Only the {cap} fugitive-only facilities with the largest releases are listed; "
        f"{left_out} more match and are not shown."
    )
    return extra if note is None else f"{note} {extra}"


def with_worker_only(
    result: InventoryResult,
    worker_only: Sequence[WorkerOnlyFacility],
    max_worker_only: int,
    state: str | None = None,
    city: str | None = None,
) -> InventoryResult:
    """The result with the fugitive-only facilities that match, capped, largest release first.

    Args:
        result: The stack view from ``rank_and_cap``; its stack figures are not changed.
        worker_only: Every fugitive-only facility found for the chemical.
        max_worker_only: Most of them kept.
        state: Keep only facilities in this state (postal abbreviation, any case).
        city: Keep only facilities in this city (any case, exact name).

    Returns:
        ``result`` with ``worker_only`` (the largest matching, at most ``max_worker_only``) and
        ``worker_only_left_out`` (how many more match); the note says so when some were left out.
    """
    wanted_state, wanted_city = _clean(state), _clean(city)
    matching = sorted(
        (w for w in worker_only if _matches(w, wanted_state, wanted_city)),
        key=_by_release,
        reverse=True,
    )
    left_out = max(0, len(matching) - max_worker_only)
    return {
        **result,
        "note": _with_cap_note(result["note"], max_worker_only, left_out),
        "worker_only": matching[:max_worker_only],
        "worker_only_left_out": left_out,
    }
