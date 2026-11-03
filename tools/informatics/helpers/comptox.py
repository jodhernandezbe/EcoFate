"""CAS -> DTXSID -> molecular weight, properties and toxicity values via the EPA CompTox API."""

from __future__ import annotations

import logging
import math
import os
import ssl
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote

import httpx

from commons.cas import format_cas
from config.loader import ComptoxSettings, ToxicityValueSpec, get_comptox_settings
from tools.credentials import COMPTOX_KEY
from tools.http import RETRYABLE_STATUS, retry_after
from tools.informatics.helpers.iris_values import disagreement, iris_values
from tools.schemas import PropertyValue, ToxicityValue

logger = logging.getLogger(__name__)

_CAS_MATCH = "CAS-RN"
_NAME_FIELD = "preferredName"  # of a CAS-search entry; the name CompTox calls the chemical by
_ZERO_RESULTS = "found 0 results"


# OpenSSL's X509_V_FLAG_NO_CHECK_TIME: skip the certificate's validity dates, nothing else.
# Python's ssl module does not name it.
_NO_CHECK_TIME = 0x200000


def tls_verification(settings: ComptoxSettings) -> ssl.SSLContext | bool:
    """How the client verifies the service's certificate: fully, or without its dates only.

    With ``accept_expired_certificate`` the chain is still validated against the system's
    trusted roots and the host name still checked; only an expired or not-yet-valid
    certificate is accepted. Verification is never turned off.
    """
    if not settings.accept_expired_certificate:
        return True
    context = ssl.create_default_context()
    context.verify_flags |= _NO_CHECK_TIME
    return context


@dataclass(frozen=True)
class Chemical:
    """A CompTox chemical verified to match a requested CAS number.

    Attributes:
        dtxsid: DSSTox substance identifier.
        preferred_name: The name CompTox reports for it; None when it gave none.
    """

    dtxsid: str
    preferred_name: str | None = None


def _number(value: object) -> float | None:
    """Return ``value`` as a float if it is a real, finite number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _text(value: object) -> str | None:
    """Return ``value`` stripped if it is real text; CompTox uses "-" for "not stated"."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped and stripped != "-" else None


def _entries(payload: object) -> list[dict[str, object]] | None:
    """Return the dict entries of a JSON list, or None if ``payload`` is not a list."""
    if not isinstance(payload, list):
        return None
    return [
        {str(k): v for k, v in cast(dict[object, object], item).items()}
        for item in cast(list[object], payload)
        if isinstance(item, dict)
    ]


def select_value(entry: Mapping[str, object]) -> PropertyValue | None:
    """Pick the experimental median of a CompTox property summary, else the predicted median.

    Args:
        entry: One element of the CompTox property summary list.

    Returns:
        The value with its unit as reported (no conversion) and its source, or None if the
        entry has neither a finite experimental nor a finite predicted median, or has no unit.
    """
    unit = entry.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        return None
    experimental = _number(entry.get("experimentalMedian"))
    if experimental is not None:
        return {"value": experimental, "unit": unit, "source": "experimental"}
    predicted = _number(entry.get("predictedMedian"))
    if predicted is not None:
        return {"value": predicted, "unit": unit, "source": "predicted"}
    return None


def _record_content(record: Mapping[str, object]) -> tuple[str, float, str] | None:
    """Return (route, value, unit) if the record has a text route, finite value and unit."""
    route = record.get("exposureRoute")
    value = _number(record.get("toxvalNumeric"))
    unit = record.get("toxvalUnits")
    if not isinstance(route, str) or value is None:
        return None
    if not isinstance(unit, str) or not unit.strip():
        return None
    return route.strip().lower(), value, unit


def _toxicity_candidate(
    record: Mapping[str, object],
    spec: ToxicityValueSpec,
) -> ToxicityValue | None:
    """Return ``record`` as a value if it matches ``spec`` by type, route and content."""
    content = _record_content(record)
    if record.get("toxvalType") not in spec.types or content is None:
        return None
    route, value, unit = content
    if route not in spec.routes:
        return None
    source = record.get("source")
    assessment = _text(record.get("riskAssessmentClass"))
    return {
        "value": value,
        "unit": unit,
        "source": source if isinstance(source, str) else "",
        "route": route,
        "endpoint": _text(record.get("toxicologicalEffect")),
        "assessment": assessment.lower() if assessment else None,
    }


def _source_rank(source: str, priority: Sequence[str], unlisted: dict[str, int]) -> int:
    """Rank a source: listed ones by priority, then unlisted ones by first appearance."""
    if source in priority:
        return priority.index(source)
    return len(priority) + unlisted.setdefault(source, len(unlisted))


def select_toxicity(
    records: Sequence[Mapping[str, object]],
    spec: ToxicityValueSpec,
    source_priority: Sequence[str],
) -> ToxicityValue | None:
    """Choose the ToxVal record for one toxicity value.

    A record qualifies when its ``toxvalType`` equals one of ``spec.types`` exactly, its
    ``exposureRoute`` (case-insensitive) is one of ``spec.routes``, and it has a finite
    ``toxvalNumeric`` and a ``toxvalUnits`` string. Among qualifying records, the best-ranked
    source wins, then the lowest or highest value per ``spec.prefer`` (the most conservative).

    Args:
        records: ToxVal records for one chemical.
        spec: The toxicity value to find.
        source_priority: ``source`` names, most preferred first. Unlisted sources rank after
            all listed ones, in the order CompTox first returned them; remaining ties keep the
            order CompTox returned.

    Returns:
        The value in ``toxvalUnits`` as reported (no conversion) with the record's source, its
        recorded exposure route, critical effect or cancer endpoint, and whether it is a
        cancer or non-cancer value; or None if no record qualifies.
    """
    unlisted: dict[str, int] = {}
    ranked: list[tuple[int, ToxicityValue]] = []
    for record in records:
        candidate = _toxicity_candidate(record, spec)
        if candidate is not None:
            ranked.append((_source_rank(candidate["source"], source_priority, unlisted), candidate))
    if not ranked:
        return None
    best_rank = min(rank for rank, _ in ranked)
    best = [item for rank, item in ranked if rank == best_rank]
    return (min if spec.prefer == "lowest" else max)(best, key=lambda item: item["value"])


def _copy_properties(values: Mapping[str, PropertyValue]) -> dict[str, PropertyValue]:
    return {
        key: {"value": v["value"], "unit": v["unit"], "source": v["source"]}
        for key, v in values.items()
    }


def _copy_toxicity(values: Mapping[str, ToxicityValue]) -> dict[str, ToxicityValue]:
    return {
        key: {
            "value": v["value"],
            "unit": v["unit"],
            "source": v["source"],
            "route": v["route"],
            "endpoint": v["endpoint"],
            "assessment": v["assessment"],
        }
        for key, v in values.items()
    }


class ComptoxLookup:
    """Fetch a chemical's molecular weight, properties and toxicity values from CompTox by CAS.

    The CAS number is validated, then resolved with CompTox's exact CAS search; only a result
    CompTox reports as a CAS-number match for that same CAS is accepted. Which properties and
    toxicity values are extracted comes from ``config/settings.toml``. Results are cached per
    CAS number and returned as copies. Found results and definitive misses (an empty result,
    HTTP 404, or HTTP 400 "found 0 results") are cached; network errors and other failures
    are not, so they can be retried.
    """

    def __init__(
        self,
        settings: ComptoxSettings | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Create a lookup.

        Args:
            settings: CompTox settings; defaults to ``config/settings.toml``.
            client: HTTP client (injectable for tests); a default one is created if omitted.
            sleep: Function used to wait ``settings.delay_seconds`` before each request.
            environ: Environment mapping the API key is read from; defaults to ``os.environ``.
        """
        self._settings = settings or get_comptox_settings()
        self._client = client or httpx.Client(
            timeout=self._settings.timeout_seconds,
            verify=tls_verification(self._settings),
        )
        self._sleep = sleep
        self._environ = os.environ if environ is None else environ
        self._chemicals: dict[str, Chemical | None] = {}
        self._weights: dict[str, float | None] = {}
        self._properties: dict[str, dict[str, PropertyValue]] = {}
        self._toxicity: dict[str, dict[str, ToxicityValue]] = {}
        self._notes: dict[str, list[str]] = {}

    def get_molecular_weight(self, cas_number: str) -> float | None:
        """Look up the molecular weight CompTox holds for a chemical.

        Args:
            cas_number: CAS registry number, e.g. "71-43-2" (hyphens optional).

        Returns:
            The value in the unit configured for it (``settings.molecular_weight.unit``,
            g/mol by default), not converted; None if the CAS number is invalid, CompTox has
            no match or no finite numeric value for it, or a request fails.

        Raises:
            RuntimeError: If the CAS number is valid and the API-key environment variable is
                unset or blank.
        """
        cas = format_cas(cas_number)
        if cas is None:
            return None
        if cas in self._weights:
            return self._weights[cas]
        headers = self._headers()
        chemical, cacheable = self._resolve(cas, headers)
        weight: float | None = None
        if chemical is not None:
            weight, cacheable = self._fetch_weight(chemical.dtxsid, headers)
        if cacheable:
            self._weights[cas] = weight
        return weight

    def get_preferred_name(self, cas_number: str) -> str | None:
        """The name CompTox calls the chemical by, from the same CAS search as its DTXSID.

        Args:
            cas_number: CAS registry number, e.g. "71-43-2" (hyphens optional).

        Returns:
            The preferred name; None if the CAS number is invalid, CompTox has no match or
            gives no name for it, or a request fails. Never a name from any other source.

        Raises:
            RuntimeError: If the CAS number is valid and the API-key environment variable is
                unset or blank.
        """
        cas = format_cas(cas_number)
        if cas is None:
            return None
        chemical, _ = self._resolve(cas, self._headers())
        return chemical.preferred_name if chemical is not None else None

    def get_properties(self, cas_number: str) -> dict[str, PropertyValue]:
        """Look up the configured properties for a chemical.

        Args:
            cas_number: CAS registry number, e.g. "71-43-2" (hyphens optional).

        Returns:
            Mapping of configured property key (e.g. "vapor_pressure") to its value, unit
            (as reported by CompTox) and source ("experimental" preferred over "predicted").
            Properties with no value are omitted. Empty if the CAS number is invalid, CompTox
            has no match, or a request fails.

        Raises:
            RuntimeError: If the CAS number is valid and the API-key environment variable is
                unset or blank.
        """
        cas = format_cas(cas_number)
        if cas is None:
            return {}
        if cas in self._properties:
            return _copy_properties(self._properties[cas])
        headers = self._headers()
        chemical, cacheable = self._resolve(cas, headers)
        result: dict[str, PropertyValue] = {}
        if chemical is not None:
            summary, cacheable = self._fetch_summary(chemical.dtxsid, headers)
            result = self._extract(summary) if summary is not None else {}
        if cacheable:
            self._properties[cas] = result
        return _copy_properties(result)

    def get_toxicity_values(self, cas_number: str) -> dict[str, ToxicityValue]:
        """Look up the configured toxicity values (RfD, RfC, SF, IUR, ...) for a chemical.

        For each value, records are filtered by type label and exposure route, the
        best-ranked source is chosen, and within it the most conservative value (lowest RfD
        and RfC, highest slope factor and unit risk, as configured).

        Args:
            cas_number: CAS registry number, e.g. "71-43-2" (hyphens optional).

        Returns:
            Mapping of configured key (e.g. "rfc") to its value, unit (as reported by
            CompTox; check it before use) and the source of the chosen record. Values with
            no qualifying record are omitted. Empty if the CAS number is invalid, CompTox has
            no match, or a request fails.

        Raises:
            RuntimeError: If the CAS number is valid and the API-key environment variable is
                unset or blank.
        """
        cas = format_cas(cas_number)
        if cas is None:
            return {}
        if cas in self._toxicity:
            return _copy_toxicity(self._toxicity[cas])
        headers = self._headers()
        chemical, cacheable = self._resolve(cas, headers)
        result: dict[str, ToxicityValue] = {}
        if chemical is not None:
            result, notes, found = self._toxicity_of(chemical.dtxsid, headers)
            cacheable = cacheable and found
            self._notes[cas] = notes
        if cacheable:
            self._toxicity[cas] = result
        return _copy_toxicity(result)

    def get_toxicity_notes(self, cas_number: str) -> list[str]:
        """Notes on the toxicity values last looked up for a chemical.

        Args:
            cas_number: CAS registry number, e.g. "71-43-2" (hyphens optional).

        Returns:
            A note for each IRIS-endpoint text that could not be read exactly and for each
            endpoint value that differs from ToxVal's copy of IRIS; empty if there is none or
            the values have not been looked up.
        """
        cas = format_cas(cas_number)
        return list(self._notes.get(cas, [])) if cas is not None else []

    def _headers(self) -> dict[str, str]:
        provided = COMPTOX_KEY.get()
        if provided is not None:  # the key of this request, resolved afresh and not kept
            return {self._settings.api_key_header: provided.get_secret_value()}
        name = self._settings.api_key_env_var
        value = self._environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"CompTox API key not set: define the {name} environment variable")
        return {self._settings.api_key_header: value}

    def _resolve(self, cas: str, headers: Mapping[str, str]) -> tuple[Chemical | None, bool]:
        """Return (verified chemical or None, definitive); caches definitive answers."""
        if cas in self._chemicals:
            return self._chemicals[cas], True
        chemical, definitive = self._fetch_chemical(cas, headers)
        if definitive:
            self._chemicals[cas] = chemical
        return chemical, definitive

    def _get_json(
        self,
        url: str,
        headers: Mapping[str, str],
        what: str,
        *,
        miss_on_zero_results: bool = False,
    ) -> tuple[object | None, bool]:
        """Return (parsed JSON or None, definitive); definitive False means a transient failure."""
        response = self._request(url, headers, what)
        if response is None:
            return None, False
        return self._parse(response, what, miss_on_zero_results)

    def _request(self, url: str, headers: Mapping[str, str], what: str) -> httpx.Response | None:
        """GET ``url``, retrying a timeout, connection error, HTTP 429 or 5xx.

        Returns the last response, or None if the last attempt got none. A response that is not
        retryable (a success, a 404, a 400) is returned at once.
        """
        retries = self._settings.max_retries
        response: httpx.Response | None = None
        for attempt in range(retries + 1):
            self._sleep(self._settings.delay_seconds)
            response = self._attempt(url, headers, what)
            if response is not None and response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt < retries:
                self._sleep(self._retry_wait(attempt, response))
        return response

    def _attempt(self, url: str, headers: Mapping[str, str], what: str) -> httpx.Response | None:
        try:
            return self._client.get(url, headers=dict(headers))
        except httpx.HTTPError as exc:
            logger.debug("CompTox %s request failed: %s", what, exc)
            return None

    def _retry_wait(self, attempt: int, response: httpx.Response | None) -> float:
        """Seconds to wait before retry ``attempt``: Retry-After (capped), else the backoff."""
        requested = retry_after(response) if response is not None else None
        if requested is None:
            return self._settings.backoff_seconds * 2**attempt
        return min(requested, self._settings.timeout_seconds)

    def _parse(
        self,
        response: httpx.Response,
        what: str,
        miss_on_zero_results: bool,
    ) -> tuple[object | None, bool]:
        status = response.status_code
        if status == 404 or (
            status == 400 and miss_on_zero_results and self._zero_results(response)
        ):
            logger.debug("CompTox has no match for %s (HTTP %s)", what, status)
            return None, True
        if status != 200:
            logger.debug("CompTox returned %s for %s", status, what)
            return None, False
        try:
            return cast(object, response.json()), True
        except ValueError:
            logger.debug("Malformed CompTox %s response", what)
            return None, False

    @staticmethod
    def _zero_results(response: httpx.Response) -> bool:
        try:
            body = cast(object, response.json())
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        detail = cast(dict[object, object], body).get("detail")
        return isinstance(detail, str) and _ZERO_RESULTS in detail.lower()

    def _fetch_chemical(self, cas: str, headers: Mapping[str, str]) -> tuple[Chemical | None, bool]:
        url = self._settings.dtxsid_by_cas_url.format(casrn=quote(cas, safe=""))
        payload, definitive = self._get_json(url, headers, "CAS search", miss_on_zero_results=True)
        if payload is None:
            return None, definitive
        entries = _entries(payload)
        if entries is None:
            logger.debug("Malformed CompTox CAS search response")
            return None, False
        for entry in entries:
            dtxsid = entry.get("dtxsid")
            if entry.get("searchName") != _CAS_MATCH or entry.get("casrn") != cas:
                continue
            if not isinstance(dtxsid, str) or not dtxsid.strip():
                continue
            return Chemical(dtxsid=dtxsid, preferred_name=_text(entry.get(_NAME_FIELD))), True
        logger.debug("No CAS-number match for %s in the CompTox response", cas)
        return None, True

    def _fetch_weight(self, dtxsid: str, headers: Mapping[str, str]) -> tuple[float | None, bool]:
        url = self._settings.detail_by_dtxsid_url.format(dtxsid=quote(dtxsid, safe=""))
        payload, definitive = self._get_json(url, headers, "chemical detail")
        if payload is None:
            return None, definitive
        if not isinstance(payload, dict):
            logger.debug("Malformed CompTox chemical detail response")
            return None, False
        detail = cast(dict[object, object], payload)
        if detail.get("dtxsid") not in (None, dtxsid):
            logger.debug("Chemical detail is for another chemical; ignored")
            return None, False
        return _number(detail.get(self._settings.molecular_weight.field)), True

    def _fetch_summary(
        self,
        dtxsid: str,
        headers: Mapping[str, str],
    ) -> tuple[Sequence[Mapping[str, object]] | None, bool]:
        url = self._settings.properties_by_dtxsid_url.format(dtxsid=quote(dtxsid, safe=""))
        payload, definitive = self._get_json(url, headers, "property search")
        if payload is None:
            return None, definitive
        entries = _entries(payload)
        if entries is None:
            logger.debug("Malformed CompTox property response")
            return None, False
        return entries, True

    def _fetch_toxval(
        self,
        dtxsid: str,
        headers: Mapping[str, str],
    ) -> tuple[Sequence[Mapping[str, object]] | None, bool]:
        url = self._settings.toxval_by_dtxsid_url.format(dtxsid=quote(dtxsid, safe=""))
        payload, definitive = self._get_json(url, headers, "ToxVal search")
        if payload is None:
            return None, definitive
        entries = _entries(payload)
        if entries is None:
            logger.debug("Malformed CompTox ToxVal response")
            return None, False
        own = [record for record in entries if record.get("dtxsid") == dtxsid]
        if len(own) != len(entries):
            logger.debug("Ignored %d ToxVal records for another chemical", len(entries) - len(own))
        return own, True

    def _fetch_iris(
        self,
        dtxsid: str,
        headers: Mapping[str, str],
    ) -> tuple[Mapping[str, object] | None, bool]:
        template = self._settings.iris_by_dtxsid_url
        if template is None:
            return None, True
        payload, definitive = self._get_json(
            template.format(dtxsid=quote(dtxsid, safe="")),
            headers,
            "IRIS search",
        )
        entries = _entries(payload) if payload is not None else None
        if payload is not None and entries is None:
            logger.debug("Malformed CompTox IRIS response")
            return None, False
        own = [r for r in entries or [] if r.get("dtxsid") in (None, dtxsid)]
        return (own[0] if own else None), definitive

    def _toxicity_of(
        self,
        dtxsid: str,
        headers: Mapping[str, str],
    ) -> tuple[dict[str, ToxicityValue], list[str], bool]:
        """(values, notes, definitive): the IRIS endpoint's chronic values ahead of ToxVal's."""
        records, toxval_done = self._fetch_toxval(dtxsid, headers)
        record, iris_done = self._fetch_iris(dtxsid, headers)
        toxval = self._extract_toxicity(records) if records is not None else {}
        values, notes = self._with_iris(toxval, records or [], record)
        return values, notes, toxval_done and iris_done

    def _with_iris(
        self,
        toxval: dict[str, ToxicityValue],
        records: Sequence[Mapping[str, object]],
        record: Mapping[str, object] | None,
    ) -> tuple[dict[str, ToxicityValue], list[str]]:
        iris = self._settings.iris
        if iris is None or record is None:
            return toxval, []
        read, notes = iris_values(record, iris, self._settings.toxicity_values)
        specs = {spec.key: spec for spec in self._settings.toxicity_values}
        for key, value in read.items():
            copy = select_toxicity(records, specs[key], (iris.toxval_source,))
            if copy is not None and copy["source"] != iris.toxval_source:
                copy = None
            note = disagreement(key, value, copy, iris.agreement_tolerance)
            notes.extend([note] if note else [])
        return {**toxval, **read}, notes

    def _extract(self, summary: Sequence[Mapping[str, object]]) -> dict[str, PropertyValue]:
        by_name: dict[str, Mapping[str, object]] = {}
        for entry in summary:
            name = entry.get("propName")
            if isinstance(name, str):
                by_name.setdefault(name, entry)
        result: dict[str, PropertyValue] = {}
        for spec in self._settings.properties:
            entry = by_name.get(spec.name)
            value = select_value(entry) if entry is not None else None
            if value is not None:
                result[spec.key] = value
        return result

    def _extract_toxicity(
        self,
        records: Sequence[Mapping[str, object]],
    ) -> dict[str, ToxicityValue]:
        result: dict[str, ToxicityValue] = {}
        for spec in self._settings.toxicity_values:
            chosen = select_toxicity(records, spec, self._settings.source_priority)
            if chosen is not None:
                result[spec.key] = chosen
        if not result and records:
            seen = sorted({str(r.get("toxvalType")) for r in records})
            logger.debug("No configured toxicity value matched; toxvalType values seen: %s", seen)
        return result
