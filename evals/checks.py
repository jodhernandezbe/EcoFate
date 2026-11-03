"""Deterministic checks on a ``RunRecord``: which tools were called, how often, with what.

Each factory returns a named ``Check``. Expected values (facilities, coordinates, stack
candidates, emission rates) are read from the tool outputs in the record, never written into
the check, so a check stays valid when the recordings change.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from evals.cassette import call_key
from evals.record import RunRecord, ToolCall

INVENTORY = "query_emissions_inventory"
NEI_STACKS = "fetch_stack_parameters_from_nei"
INDUSTRY = "fetch_facility_industry"
SCC_LOOKUP = "lookup_scc_process_description"
SCC_STACK = "fetch_stack_parameters_from_scc"
METEOROLOGY = "get_meteorological_boundary"
POPULATION = "get_population_receptors"
EXPOSURE = "calculate_exposure_metrics"
ASSESSMENT = "assess_facilities"
PROPERTIES = "fetch_chemical_properties"
STACK_FIELDS = ("stack_height", "stack_diameter", "exit_velocity", "exit_temperature")
_REL_TOL = 1e-9


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check: pass or fail, with the reason."""

    passed: bool
    reason: str


@dataclass(frozen=True)
class Check:
    """A named deterministic check."""

    name: str
    evaluate: Callable[[RunRecord], CheckResult]


Facility = Mapping[str, object]


def _verdict(problems: Sequence[str], ok: str) -> CheckResult:
    return CheckResult(False, "; ".join(problems)) if problems else CheckResult(True, ok)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _close(a: object, b: object) -> bool:
    x, y = _number(a), _number(b)
    return x is not None and y is not None and math.isclose(x, y, rel_tol=_REL_TOL)


def _mapping(value: object) -> Facility:
    return cast(Facility, value) if isinstance(value, dict) else {}


def _dicts(value: object) -> list[Facility]:
    if isinstance(value, dict):  # the inventory's {"facilities": [...], ...} shape
        value = cast(dict[str, object], value).get("facilities")
    items = cast(list[object], value) if isinstance(value, list) else []
    return [cast(Facility, item) for item in items if isinstance(item, dict)]


def _label(call: ToolCall) -> str:
    return f"{call.name}({call_key(call.args)})"


def inventory_facilities(record: RunRecord) -> dict[str, Facility]:
    """Facilities returned by the emissions inventory, keyed by FRS ID."""
    return {
        str(f.get("frs_id")): f for call in record.calls_to(INVENTORY) for f in _dicts(call.output)
    }


def assessed_candidates(record: RunRecord) -> dict[str, list[Facility]]:
    """NEI stack candidates of each facility whose stacks the agent requested, by FRS ID."""
    found: dict[str, list[Facility]] = {}
    for call in record.calls_to(NEI_STACKS):
        found[str(call.args.get("frs_id")).strip()] = _dicts(
            _mapping(call.output).get("candidates"),
        )
    return found


def asks_for_missing(quantity: str) -> Check:
    """The reply names the missing value and offers both answers: enter it, or proceed without."""

    def evaluate(record: RunRecord) -> CheckResult:
        text = record.report.lower()
        problems: list[str] = []
        if quantity not in text:
            problems.append(f"the reply does not name {quantity}")
        if "proceed without" not in text:
            problems.append("the reply does not offer to proceed without it")
        return _verdict(problems, f"the reply asks for {quantity} and offers both answers")

    return Check(f"asks for {quantity}", evaluate)


def completed() -> Check:
    """The run finished with a final report and no error."""

    def evaluate(record: RunRecord) -> CheckResult:
        if record.completed:
            return CheckResult(True, "run completed")
        return CheckResult(False, f"run did not finish: {record.error or 'empty report'}")

    return Check("run completed", evaluate)


def no_unrecorded() -> Check:
    """Every replayed call had a recording (else re-record the scenario)."""

    def evaluate(record: RunRecord) -> CheckResult:
        missing = [_label(c) for c in record.calls if c.unrecorded]
        problems = [f"unrecorded calls, re-record the scenario: {', '.join(missing)}"]
        return _verdict(problems if missing else [], "every call had a recording")

    return Check("no unrecorded call", evaluate)


def called_with(tool: str, **expected: object) -> Check:
    """At least one call to ``tool`` carries ``expected`` (compared as stripped strings)."""
    wanted = {k: str(v).strip() for k, v in expected.items()}

    def matches(call: ToolCall) -> bool:
        return all(str(call.args.get(k)).strip() == v for k, v in wanted.items())

    def evaluate(record: RunRecord) -> CheckResult:
        calls = record.calls_to(tool)
        if any(matches(c) for c in calls):
            return CheckResult(True, f"{tool} called with {wanted}")
        seen = ", ".join(_label(c) for c in calls) or "no call"
        return CheckResult(False, f"{tool} never called with {wanted} (seen: {seen})")

    return Check(f"{tool} called with {wanted}", evaluate)


def not_called(*tools: str) -> Check:
    """None of ``tools`` is called."""

    def evaluate(record: RunRecord) -> CheckResult:
        forbidden = [_label(c) for c in record.calls if c.name in tools]
        problems = [f"forbidden calls: {', '.join(forbidden)}"] if forbidden else []
        return _verdict(problems, f"none of {', '.join(tools)} called")

    return Check(f"not called: {', '.join(tools)}", evaluate)


def no_tool_called() -> Check:
    """The agent answered without calling any tool."""

    def evaluate(record: RunRecord) -> CheckResult:
        calls = [_label(c) for c in record.calls]
        problems = [f"tools called: {', '.join(calls)}"] if calls else []
        return _verdict(problems, "no tool called")

    return Check("no tool called", evaluate)


def _at_point(record: RunRecord, tool: str, facility: Facility) -> bool:
    return any(
        _close(c.args.get("latitude"), facility.get("latitude"))
        and _close(c.args.get("longitude"), facility.get("longitude"))
        for c in record.calls_to(tool)
    )


def _site_problems(record: RunRecord, frs_id: str, facility: Facility | None) -> list[str]:
    if facility is None:
        return [f"stacks requested for {frs_id}, which the inventory did not return"]
    return [
        f"{tool} not called at the coordinates of {frs_id}"
        for tool in (METEOROLOGY, POPULATION)
        if not _at_point(record, tool, facility)
    ]


def site_inputs_per_assessed_facility() -> Check:
    """Each facility whose stacks were requested is an inventory facility and gets weather and
    population requested at its own coordinates."""

    def evaluate(record: RunRecord) -> CheckResult:
        facilities = inventory_facilities(record)
        assessed = assessed_candidates(record)
        if not assessed and record.calls_to(ASSESSMENT):
            return CheckResult(True, "the batch assessment gathered the site inputs")
        if not assessed:
            return CheckResult(False, "no facility had its NEI stacks requested")
        problems = [p for frs in assessed for p in _site_problems(record, frs, facilities.get(frs))]
        return _verdict(problems, f"weather and population at each of {len(assessed)} sites")

    return Check("weather and population per assessed facility", evaluate)


def _same_stack(a: Facility, b: Facility) -> bool:
    return all(_close(a.get(f), b.get(f)) for f in STACK_FIELDS)


def _carries(call: ToolCall, candidate: Facility) -> bool:
    return any(_same_stack(stack, candidate) for stack in _dicts(call.args.get("stacks")))


def _facility_calls(
    record: RunRecord,
    facility: Facility,
    candidates: list[Facility],
) -> list[ToolCall]:
    """Exposure calls for this facility: its emission rate and at least one of its stacks."""
    return [
        call
        for call in record.calls_to(EXPOSURE)
        if _close(call.args.get("emission_rate"), facility.get("emission_rate"))
        and any(_carries(call, candidate) for candidate in candidates)
    ]


def _coverage_problems(record: RunRecord, frs_id: str, facility: Facility) -> list[str]:
    candidates = assessed_candidates(record).get(frs_id, [])
    if not candidates:
        return []
    calls = _facility_calls(record, facility, candidates)
    if len(calls) != 1:
        return [f"{frs_id}: {len(calls)} exposure calls with its emission rate, expected 1"]
    missing = [str(n) for n, c in enumerate(candidates, start=1) if not _carries(calls[0], c)]
    if missing:
        return [f"{frs_id}: candidates {', '.join(missing)} of {len(candidates)} not passed"]
    return []


def exposure_covers_every_candidate() -> Check:
    """Each assessed facility with NEI candidates gets exactly one exposure call carrying every
    candidate and the facility's emission rate (candidates and rates from the record)."""

    def evaluate(record: RunRecord) -> CheckResult:
        facilities = inventory_facilities(record)
        assessed = [frs for frs in assessed_candidates(record) if frs in facilities]
        problems = [p for frs in assessed for p in _coverage_problems(record, frs, facilities[frs])]
        total = sum(len(assessed_candidates(record)[frs]) for frs in assessed)
        return _verdict(problems, f"all {total} NEI candidates passed, one call per facility")

    return Check("one exposure call per facility with every NEI candidate", evaluate)


def _with_candidates(record: RunRecord) -> tuple[set[str], bool]:
    """Control numbers of assessed facilities with NEI candidates; True if every one has some."""
    facilities = inventory_facilities(record)
    assessed = assessed_candidates(record)
    covered = {
        str(facilities[frs].get("doc_ctrl_num")).strip()
        for frs, candidates in assessed.items()
        if candidates and frs in facilities
    }
    return covered, all(assessed.values())


def no_fallback_for_facilities_with_candidates() -> Check:
    """No industry lookup for a facility that has NEI candidates, and no SCC search or SCC stack
    when every assessed facility has them."""

    def evaluate(record: RunRecord) -> CheckResult:
        covered, all_covered = _with_candidates(record)
        problems = [
            f"unneeded {_label(c)}"
            for c in record.calls_to(INDUSTRY)
            if str(c.args.get("doc_ctrl_num")).strip() in covered
        ]
        if all_covered:
            problems += [
                f"unneeded {_label(c)}" for c in record.calls if c.name in {SCC_LOOKUP, SCC_STACK}
            ]
        return _verdict(problems, "no fallback for facilities with their own stacks")

    return Check("no fallback for facilities with NEI stacks", evaluate)


def batch_facilities(record: RunRecord) -> list[Facility]:
    """Facilities the batch assessment returned, fully assessed and at worst case only."""
    found: list[Facility] = []
    for call in record.calls_to(ASSESSMENT):
        output = _mapping(call.output)
        found += _dicts(output.get("facilities")) + _dicts(output.get("worst_case_only"))
    return found


def _batch_unaccounted(record: RunRecord) -> list[str]:
    """Batch results whose counts (assessed, worst case, screened out) miss some facility."""
    problems: list[str] = []
    for call in record.calls_to(ASSESSMENT):
        output = _mapping(call.output)
        screening = _mapping(output.get("screening"))
        covered = (
            len(batch_facilities(record))
            + len(_dicts(output.get("not_assessed")))
            + (_number(screening.get("screened_out_at_bound")) or 0)
            + (_number(screening.get("screened_out_with_own_stacks")) or 0)
        )
        found = _number(output.get("facilities_found")) or 0
        if covered < found:
            problems.append(f"{int(found - covered)} of {int(found)} facilities unaccounted for")
    return problems


def screened_out(record: RunRecord) -> int:
    """Facilities the batch assessment screened out, on the bound or with their own stacks."""
    total = 0.0
    for call in record.calls_to(ASSESSMENT):
        screening = _mapping(_mapping(call.output).get("screening"))
        total += (_number(screening.get("screened_out_at_bound")) or 0) + (
            _number(screening.get("screened_out_with_own_stacks")) or 0
        )
    return int(total)


def _by_hand(record: RunRecord, facility: Facility) -> bool:
    """Whether an exposure call carried this facility's emission rate (the manual route)."""
    return any(
        _close(c.args.get("emission_rate"), facility.get("emission_rate"))
        for c in record.calls_to(EXPOSURE)
    )


def covered_facilities(record: RunRecord) -> dict[str, Facility]:
    """Inventory facilities assessed by either route, plus the batch tool's own, by FRS ID."""
    covered = {str(f.get("frs_id")): f for f in batch_facilities(record)}
    for frs_id, facility in inventory_facilities(record).items():
        if frs_id in covered or _by_hand(record, facility):
            covered[frs_id] = facility
    return covered


def every_facility_covered() -> Check:
    """Every inventory facility is assessed (by the batch tool or by hand) or accounted for
    by the batch tool's screening counts; nothing is dropped silently."""

    def evaluate(record: RunRecord) -> CheckResult:
        inventory = inventory_facilities(record)
        covered = covered_facilities(record)
        if record.calls_to(ASSESSMENT):
            problems = _batch_unaccounted(record)
        elif inventory:
            missing = [frs for frs in inventory if frs not in covered]
            problems = [f"not assessed: {', '.join(missing)}"] if missing else []
        else:
            problems = ["neither the inventory nor the batch assessment was called"]
        done = f"{len(covered)} facilities assessed, {screened_out(record)} screened out"
        return _verdict(problems, f"{done}, none dropped")

    return Check("every facility covered", evaluate)


def _named(report: str, facility: Facility) -> bool:
    text = report.lower()
    frs, name = str(facility.get("frs_id") or ""), str(facility.get("facility_name") or "")
    return bool(frs and frs in report) or bool(name.strip() and name.strip().lower() in text)


def every_covered_facility_reported() -> Check:
    """The report names every facility that was assessed (by FRS ID or name)."""

    def evaluate(record: RunRecord) -> CheckResult:
        covered = covered_facilities(record)
        if not covered and screened_out(record):
            return CheckResult(True, f"nothing to name: {screened_out(record)} screened out")
        if not covered:
            return CheckResult(False, "no facility was assessed")
        missing = [frs for frs, f in covered.items() if not _named(record.report, f)]
        problems = [f"not in the report: {', '.join(missing)}"] if missing else []
        return _verdict(problems, f"all {len(covered)} assessed facilities reported")

    return Check("every assessed facility reported", evaluate)


_GENERIC_WORDS = frozenset({"reanalysis", "data", "year", "from", "with", "tracts", "tract"})
_NOT_A_SOURCE = "not requested"  # a batch facility kept at the worst case has no site weather


def _tokens(text: str) -> list[str]:
    """The distinctive words of a source text: 4+ characters, not generic, lower-cased."""
    words = re.findall(r"[a-z0-9][a-z0-9-]{3,}", text.lower())
    return [w for w in words if w not in _GENERIC_WORDS]


def _mentions(report: str, text: str) -> bool:
    """Whether the report carries at least one distinctive word of the source text."""
    tokens = _tokens(text)
    return not tokens or any(t in report.lower() for t in tokens)


def _batch_sources(record: RunRecord) -> list[tuple[str, str]]:
    """Source texts the batch assessment reports: site weather, and the screen's own."""
    found: list[tuple[str, str]] = []
    for call in record.calls_to(ASSESSMENT):
        output = _mapping(call.output)
        for facility in _dicts(output.get("facilities")):
            source = str(facility.get("weather_source") or "")
            if source and not source.startswith(_NOT_A_SOURCE):
                found.append(("weather", source))
        if screened_out(record):
            found.append(("screening bound", "AirToxScreen SCREEN3"))
    return found


def input_sources(record: RunRecord) -> list[tuple[str, str]]:
    """(label, source text) of every input the run obtained, from the record's tool outputs."""
    found: list[tuple[str, str]] = []
    for tool, label in ((METEOROLOGY, "weather"), (POPULATION, "residents")):
        found += [
            (label, str(_mapping(c.output).get("source") or "")) for c in record.calls_to(tool)
        ]
    for call in record.calls_to(PROPERTIES):
        sources = _mapping(_mapping(call.output).get("sources"))
        found += [(f"benchmark {k}", str(v)) for k, v in sources.items() if k in ("rfc", "iur")]
    return [*found, *_batch_sources(record)]


def _name_problems(record: RunRecord) -> list[str]:
    """The chemical is called what the properties result calls it, else by its CAS number."""
    problems: list[str] = []
    for call in record.calls_to(PROPERTIES):
        name = _mapping(call.output).get("preferred_name")
        cas = str(call.args.get("cas_number") or "").strip()
        if isinstance(name, str) and name.strip():
            if name.strip().lower() not in record.report.lower():
                problems.append(f"the chemical's name {name!r} is not in the report")
        elif re.search(rf"{re.escape(cas)}\s*\(|\bknown as\b", record.report, re.I):
            problems.append(
                f"the report names the chemical although no result gave CAS {cas} a name",
            )
    return problems


def report_names_each_source() -> Check:
    """The report names the source of each input as the results give it, and calls the
    chemical by the name the properties result gave (or by its CAS number alone)."""

    def evaluate(record: RunRecord) -> CheckResult:
        sources = {text: label for label, text in input_sources(record) if text}
        problems = [
            f"{label} source not named: {text!r}"
            for text, label in sources.items()
            if not _mentions(record.report, text)
        ]
        problems += _name_problems(record)
        return _verdict(problems, f"all {len(sources)} input sources named")

    return Check("report names each input source", evaluate)
