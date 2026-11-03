"""Tests for the CompTox retry policy and the source priority (no network, no real waits)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import httpx
import pytest

from config.loader import get_comptox_settings
from tools.informatics.helpers.comptox import ComptoxLookup, select_toxicity

CAS = "71-43-2"
DTX = "DTXSID0"
KEY = {"TEST_KEY_VAR": "test-key"}  # pragma: allowlist secret
RFC = {
    "dtxsid": DTX,
    "toxvalType": "RfC",
    "toxvalNumeric": 0.5,
    "toxvalUnits": "mg/m3",
    "exposureRoute": "inhalation",
    "source": "EPA IRIS: IRIS",
}
CHEM = [{"dtxsid": DTX, "casrn": CAS, "searchName": "CAS-RN"}]


@dataclass
class Service:
    """A scripted CompTox: per path prefix, the answers in order (the last repeats)."""

    script: dict[str, list[httpx.Response | Exception]]
    requests: list[str] = field(default_factory=lambda: [])
    sleeps: list[float] = field(default_factory=lambda: [])

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        for prefix, answers in self.script.items():
            if request.url.path.startswith(prefix):
                item = answers.pop(0) if len(answers) > 1 else answers[0]
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"unscripted {request.url.path}")

    def lookup(
        self,
        retries: int = 2,
        backoff: float = 3.0,
        with_iris: bool = False,
    ) -> ComptoxLookup:
        settings = replace(
            get_comptox_settings(),
            iris=get_comptox_settings().iris if with_iris else None,
            max_retries=retries,
            backoff_seconds=backoff,
            delay_seconds=0.2,
            timeout_seconds=10.0,
            api_key_env_var="TEST_KEY_VAR",  # pragma: allowlist secret
        )
        client = httpx.Client(transport=httpx.MockTransport(self.respond))
        return ComptoxLookup(settings, client, sleep=self.sleeps.append, environ=KEY)

    def count(self, prefix: str) -> int:
        return sum(1 for path in self.requests if path.startswith(prefix))


def _ok(body: object) -> httpx.Response:
    return httpx.Response(200, json=body)


SEARCH = "/ctx-api/chemical/search"
TOXVAL = "/ctx-api/hazard/toxval"


def _timeout() -> Exception:
    return httpx.ReadTimeout("slow")


def test_connection_error_then_success() -> None:
    service = Service({SEARCH: [httpx.ConnectError("reset"), _ok(CHEM)], TOXVAL: [_ok([RFC])]})
    result = service.lookup().get_toxicity_values(CAS)
    assert result["rfc"]["value"] == 0.5 and service.count(SEARCH) == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_status_then_success(status: int) -> None:
    service = Service({SEARCH: [_ok(CHEM)], TOXVAL: [httpx.Response(status), _ok([RFC])]})
    assert service.lookup().get_toxicity_values(CAS)["rfc"]["value"] == 0.5
    assert service.count(TOXVAL) == 2


def test_exhausted_retries_return_nothing_and_cache_nothing() -> None:
    service = Service({SEARCH: [_ok(CHEM)], TOXVAL: [httpx.Response(503)]})
    lookup = service.lookup(retries=2)
    assert lookup.get_toxicity_values(CAS) == {}
    assert service.count(TOXVAL) == 3
    assert lookup.get_toxicity_values(CAS) == {}
    assert service.count(TOXVAL) == 6  # a later call contacts CompTox again


def test_timeouts_are_retried_and_end_without_raising() -> None:
    service = Service({SEARCH: [_timeout()]})
    assert service.lookup(retries=1).get_toxicity_values(CAS) == {}
    assert service.count(SEARCH) == 2


def test_no_retries_configured_means_one_attempt() -> None:
    service = Service({SEARCH: [httpx.Response(503)]})
    assert service.lookup(retries=0).get_toxicity_values(CAS) == {}
    assert service.count(SEARCH) == 1


@pytest.mark.parametrize("status", [404, 401, 403, 422])
def test_definitive_or_client_errors_are_not_retried(status: int) -> None:
    service = Service({SEARCH: [httpx.Response(status)]})
    assert service.lookup().get_toxicity_values(CAS) == {}
    assert service.count(SEARCH) == 1


def test_zero_results_answer_is_final_and_cached() -> None:
    body = {"detail": "Searched by CASRN: Found 0 results for 'x'."}
    service = Service({SEARCH: [httpx.Response(400, json=body)]})
    lookup = service.lookup()
    assert lookup.get_toxicity_values(CAS) == {}
    assert lookup.get_toxicity_values(CAS) == {}
    assert service.count(SEARCH) == 1


def test_other_400_answers_are_not_retried_or_cached() -> None:
    service = Service({SEARCH: [httpx.Response(400, json={"detail": "bad"})]})
    lookup = service.lookup()
    assert lookup.get_toxicity_values(CAS) == {}
    assert service.count(SEARCH) == 1
    lookup.get_toxicity_values(CAS)
    assert service.count(SEARCH) == 2


def test_waits_are_the_delay_then_a_doubling_backoff() -> None:
    service = Service({SEARCH: [httpx.Response(503)]})
    service.lookup(retries=2, backoff=3.0).get_toxicity_values(CAS)
    assert service.sleeps == [0.2, 3.0, 0.2, 6.0, 0.2]


def test_retry_after_is_honoured_up_to_the_timeout() -> None:
    slow = httpx.Response(429, headers={"Retry-After": "4"})
    very_slow = httpx.Response(429, headers={"Retry-After": "999"})
    service = Service({SEARCH: [slow, very_slow, httpx.Response(429)]})
    service.lookup(retries=2, backoff=3.0).get_toxicity_values(CAS)
    assert service.sleeps == [0.2, 4.0, 0.2, 10.0, 0.2]


@pytest.mark.parametrize("header", ["soon", "-5", ""])
def test_unusable_retry_after_falls_back_to_the_backoff(header: str) -> None:
    service = Service({SEARCH: [httpx.Response(429, headers={"Retry-After": header})]})
    service.lookup(retries=1, backoff=3.0).get_toxicity_values(CAS)
    assert service.sleeps == [0.2, 3.0, 0.2]


def test_one_flaky_request_does_not_lose_the_others() -> None:
    detail = {"dtxsid": DTX, "averageMass": 78.0}
    service = Service(
        {
            SEARCH: [_ok(CHEM)],
            "/ctx-api/chemical/detail": [httpx.Response(502), _ok(detail)],
            TOXVAL: [_ok([RFC])],
        },
    )
    lookup = service.lookup()
    assert lookup.get_molecular_weight(CAS) == 78.0
    assert lookup.get_toxicity_values(CAS)["rfc"]["value"] == 0.5


# --- source priority -------------------------------------------------------------------------


def _record(source: str, value: float) -> dict[str, object]:
    return {**RFC, "source": source, "toxvalNumeric": value}


def test_shipped_priority_prefers_the_api_named_iris_record() -> None:
    settings = get_comptox_settings()
    rfc = next(spec for spec in settings.toxicity_values if spec.key == "rfc")
    records = [_record("Alaska DEC: Alaska DEC", 0.01), _record("EPA IRIS: IRIS", 0.5)]
    chosen = select_toxicity(records, rfc, settings.source_priority)
    assert chosen is not None
    assert (chosen["value"], chosen["source"]) == (0.5, "EPA IRIS: IRIS")


def test_the_old_short_name_would_not_have_matched() -> None:
    settings = get_comptox_settings()
    rfc = next(spec for spec in settings.toxicity_values if spec.key == "rfc")
    records = [_record("Alaska DEC: Alaska DEC", 0.01), _record("EPA IRIS: IRIS", 0.5)]
    chosen = select_toxicity(records, rfc, ("IRIS",))
    assert chosen is not None and chosen["source"] == "Alaska DEC: Alaska DEC"
