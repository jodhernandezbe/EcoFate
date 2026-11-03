"""Tests for fetch_facility_industry (no network: a mock Envirofacts)."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from config.industry import IndustrySettings, get_industry_settings
from tools.emissions import industry
from tools.emissions.industry import fetch_facility_industry

DOC = "1313000000001"
REAL = get_industry_settings()


@pytest.fixture
def requests_seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "REF_NAICS" in request.url.path:
            code = request.url.path.split("/NAICS_CODE/")[1].split("/")[0]
            return httpx.Response(
                200,
                json=[{"naics_code": code, "naics_desc": f"Title of {code}"}],
            )
        # A path of the form /sub/{code}/... reports that code; the default is a listed one.
        parts = request.url.path.split("/sub/")
        row = {
            "naics_code": parts[1].split("/")[0] if len(parts) > 1 else "324110",
            "primary_ind": "1",
            "naics_sequence_num": 1,
            "source": "Reported",
        }
        return httpx.Response(200, json=[row])

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(industry, "_open_client", lambda: httpx.Client(transport=transport))
    return seen


def _only_submission(code: str) -> IndustrySettings:
    """Settings under which the mock submission reports ``code`` (not in the local lists)."""
    return replace(REAL, submission_naics_path=f"/sub/{code}/{{doc_ctrl_num}}/JSON")


def test_schema() -> None:
    assert fetch_facility_industry.name == "fetch_facility_industry"
    assert set(fetch_facility_industry.args) == {"doc_ctrl_num"}


def test_returns_the_title_in_words(requests_seen: list[httpx.Request]) -> None:
    result = fetch_facility_industry.invoke({"doc_ctrl_num": DOC})
    assert result["naics_code"] == "324110"
    assert result["naics_title"] == "Petroleum Refineries"
    assert result["code_origin"] == "reported"
    assert result["source"] == "TRI submission NAICS"
    assert result["warnings"] == []
    # The title came from the local Census code lists: only the submission row was requested.
    assert len(requests_seen) == 1


def test_a_code_the_local_lists_lack_is_looked_up_in_the_reference_table(
    requests_seen: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(industry, "get_industry_settings", lambda: _only_submission("123456"))
    result = fetch_facility_industry.invoke({"doc_ctrl_num": DOC})
    assert result["naics_title"] == "Title of 123456"
    assert len(requests_seen) == 2


def test_accepts_a_number(requests_seen: list[httpx.Request]) -> None:
    assert (
        fetch_facility_industry.invoke({"doc_ctrl_num": 1313000000001})["naics_title"]
        == "Petroleum Refineries"
    )


def test_an_invalid_number_returns_nulls_without_a_request(
    requests_seen: list[httpx.Request],
) -> None:
    result = fetch_facility_industry.invoke({"doc_ctrl_num": "abc"})
    assert result["naics_code"] is None and result["naics_title"] is None
    assert result["warnings"] and requests_seen == []


def test_description_says_what_to_do_with_the_result() -> None:
    text = " ".join(fetch_facility_industry.description.split())
    for phrase in ("`naics_title`", "SCC process search", "`doc_ctrl_num`", "null", "do not guess"):
        assert phrase in text, phrase
