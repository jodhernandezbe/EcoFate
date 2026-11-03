"""Projector of the batch assessment: every facility's chain, filed like the single tools'.

The artifact holds the assessed facilities (fully, or at their own-stack worst case only) and
the screened-out ones with their screening value; an earlier form was the list of assessed
facilities alone, and is still read. A facility the batch did not assess travels with its
reason; it never replaces a real result for the same facility.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from api.schemas.workspace import Screening, ScreeningOutcome
from api.services.projectors.ledger import Ledger, Located, Receptor, ToolExchange, text
from api.services.projectors.payloads import (
    AssessedPayload,
    EmissionPayload,
    NotAssessedPayload,
    OccupationalPayload,
    ProfilePayload,
    ScreenedOutPayload,
    WorstCaseScenarioPayload,
    validate,
)

_LEFT_OUT = "A facility of the batch assessment was left out: its result was not valid."


def _place(record: EmissionPayload, ledger: Ledger, cas: str | None) -> None:
    ledger.facilities[record.frs_id] = record
    if cas is not None:
        ledger.facility_cas[record.frs_id] = cas


def _site(item: AssessedPayload, ledger: Ledger) -> None:
    """The weather and residents at the facility, when the chain gathered them."""
    record = item.record
    point = (record.latitude, record.longitude)
    if item.meteorology is not None:
        ledger.meteorology.append(Located(*point, item.meteorology))
    if item.population is not None:
        radius = ledger.default_radius_km if item.radius_km is None else item.radius_km
        ledger.population.append(Receptor(Located(*point, item.population), radius))


def _keep[T](
    raw: object,
    model: type[T],
    store: dict[str, T],
    frs_id: str,
    ledger: Ledger,
    name: str,
) -> None:
    """File ``raw`` as ``model``; an invalid one is left out alone, with a warning."""
    if raw is None:
        return
    parsed = validate(model, raw)
    if parsed is None:
        ledger.warnings.append(f"Left out the {name} of facility {frs_id}: it was not valid.")
    else:
        store[frs_id] = parsed


def _worker(item: AssessedPayload, ledger: Ledger) -> None:
    """The worker screening and the operational profile of one facility."""
    frs_id = item.record.frs_id
    _keep(
        item.occupational_exposure,
        OccupationalPayload,
        ledger.worker,
        frs_id,
        ledger,
        "worker exposure",
    )
    _keep(
        item.operational_profile,
        ProfilePayload,
        ledger.profiles,
        frs_id,
        ledger,
        "operational profile",
    )


def _scenarios(item: AssessedPayload, ledger: Ledger) -> None:
    """The facility's worst-case scenarios; an invalid one is left out alone, with a warning."""
    frs_id = item.record.frs_id
    for raw in item.scenarios:
        parsed = validate(WorstCaseScenarioPayload, raw)
        if parsed is None:
            ledger.warnings.append(
                f"Left out a worst-case scenario of facility {frs_id}: it was not valid.",
            )
        else:
            ledger.scenarios.setdefault(frs_id, []).append(parsed)


def _results(item: AssessedPayload, ledger: Ledger) -> None:
    """The worker screening, the operational profile and the scenarios of one facility."""
    _worker(item, ledger)
    _scenarios(item, ledger)


def _file(item: AssessedPayload, ledger: Ledger, cas: str | None) -> None:
    """One facility's results, keyed so they attach to that facility only."""
    record = item.record
    frs_id = record.frs_id
    _place(record, ledger, cas)
    ledger.nei.append((frs_id, item.stacks))
    for match in item.scc_matches:
        ledger.scc_matches[match.scc] = match
    if item.industry is not None and record.doc_ctrl_num is not None:
        ledger.industries.append((record.doc_ctrl_num, item.industry))
    _site(item, ledger)
    _results(item, ledger)
    ledger.exposures.append((frs_id, item.exposure))
    outcome: ScreeningOutcome = "full" if item.level == "full" else "worst_case_only"
    bound = item.bound
    ledger.screening[frs_id] = Screening(
        outcome=outcome,
        bound_hq=bound.hq if bound else None,
        bound_cancer_risk=bound.cancer_risk if bound else None,
    )


def _file_out(item: ScreenedOutPayload, ledger: Ledger, cas: str | None) -> None:
    """A screened-out facility: placed, with its own stacks if it has them, and why."""
    frs_id = item.record.frs_id
    _place(item.record, ledger, cas)
    if item.stacks:
        ledger.nei.append((frs_id, item.stacks))
    at_bound = item.stage == "bound"
    ledger.screening[frs_id] = Screening(
        outcome="screened_out_at_bound" if at_bound else "screened_out_with_own_stacks",
        bound_hq=item.hq if at_bound else None,
        bound_cancer_risk=item.cancer_risk if at_bound else None,
        value_hq=item.hq,
        value_cancer_risk=item.cancer_risk,
        reason=item.reason,
    )


def _list(body: Mapping[str, object], key: str) -> list[object] | None:
    value = body.get(key, [])
    return cast(list[object], value) if isinstance(value, list) else None


def _parts(artifact: object) -> tuple[list[object], list[object], list[object]] | None:
    """The assessed, screened-out and not-assessed items; None when the artifact has no shape."""
    if isinstance(artifact, list):
        return cast(list[object], artifact), [], []
    if not isinstance(artifact, Mapping):
        return None
    body = cast(Mapping[str, object], artifact)
    assessed, out, left = (
        _list(body, "assessed"),
        _list(body, "screened_out"),
        _list(body, "not_assessed"),
    )
    if assessed is None or out is None or left is None or "assessed" not in body:
        return None
    return assessed, out, left


def _file_unassessed(item: NotAssessedPayload, ledger: Ledger) -> None:
    """A facility with no result: its reason, unless a real result is already filed for it."""
    if item.frs_id not in ledger.screening:
        ledger.screening[item.frs_id] = Screening(outcome="not_assessed", reason=item.reason)


def _each[T](model: type[T], raws: list[object], ledger: Ledger, file: Callable[[T], None]) -> None:
    for raw in raws:
        item = validate(model, raw)
        if item is None:
            ledger.warnings.append(_LEFT_OUT)
        else:
            file(item)


def project_assessment(exchange: ToolExchange, ledger: Ledger) -> None:
    """Every facility of the call, from the complete artifact (the model's text is a summary)."""
    parts = _parts(exchange.artifact)
    if parts is None:
        ledger.skip(exchange, "it carried no facility details")
        return
    ledger.note_cas(exchange)
    cas = text(exchange.args, "cas_number")
    _each(AssessedPayload, parts[0], ledger, lambda item: _file(item, ledger, cas))
    _each(ScreenedOutPayload, parts[1], ledger, lambda item: _file_out(item, ledger, cas))
    _each(NotAssessedPayload, parts[2], ledger, lambda item: _file_unassessed(item, ledger))
