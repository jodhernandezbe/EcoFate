"""Tests for tools.emissions.helpers.industry.naics (no network: an httpx mock transport).

Control numbers are fake; NAICS codes and titles are public reference text. The row shapes are
the ones Envirofacts returns for ``tri_submission_naics``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import httpx
import pytest

from config.efservice import load_efservice_settings
from config.industry import IndustrySettings, load_industry_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.industry import naics
from tools.emissions.helpers.industry.naics import SOURCE, submission_industry
from tools.schemas import FacilityIndustry

SETTINGS = load_industry_settings()
LOCAL_TITLES = naics.naics_titles


def _no_titles(_settings: IndustrySettings) -> Mapping[str, str]:
    return {}


@pytest.fixture(autouse=True)
def no_local_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reference-table behaviour is tested with empty local lists; see the local tests."""
    monkeypatch.setattr(naics, "naics_titles", _no_titles)


EF = replace(
    load_efservice_settings(),
    base_url="https://ef.test",
    delay_seconds=0.0,
    max_retries=0,
)
DOC = "1313000000001"
TITLES = {
    "324110": "Petroleum Refineries",
    "325412": "Pharmaceutical Preparation Manufacturing",
    "335999": "All Other Miscellaneous Electrical Equipment and Component Manufacturing",
    "339999": "All Other Miscellaneous Manufacturing",
    "313310": "Textile and Fabric Finishing Mills",
}


def _row(
    code: object,
    *,
    source: object = "Reported",
    primary: object = "1",
    sequence: object = 1,
) -> dict[str, object]:
    return {
        "doc_ctrl_num": DOC,
        "naics_code": code,
        "naics_sequence_num": sequence,
        "primary_ind": primary,
        "source": source,
        "method": None,
    }


class Service:
    """A mock Envirofacts: a submission's NAICS rows and the reference titles; logs requests."""

    def __init__(
        self,
        rows: object,
        titles: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        self.rows = rows
        self.titles = TITLES if titles is None else titles
        self.status = status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if "REF_NAICS" in path:
            code = path.split("/NAICS_CODE/")[1].split("/")[0]
            title = self.titles.get(code)
            body = [{"naics_code": code, "naics_desc": title, "status_flag": "A"}] if title else []
            return httpx.Response(200, json=body)
        return httpx.Response(self.status, json=self.rows)

    def run(self, doc: str | int = DOC, settings: IndustrySettings = SETTINGS) -> FacilityIndustry:
        http = httpx.Client(transport=httpx.MockTransport(self.handle))
        return submission_industry(doc, EfserviceClient(EF, http, lambda _s: None), settings)

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def test_a_reported_code_gives_code_title_and_origin() -> None:
    service = Service([_row("324110")])
    assert service.run() == FacilityIndustry(
        naics_code="324110",
        naics_title="Petroleum Refineries",
        code_origin="reported",
        source=SOURCE,
        warnings=[],
    )
    assert service.paths == [
        f"/tri_submission_naics/primary_ind/1/doc_ctrl_num/{DOC}/JSON",
        "/REF_NAICS/NAICS_CODE/324110/JSON",
    ]


def test_the_query_asks_for_the_submissions_primary_row_only() -> None:
    service = Service([_row("324110")])
    service.run()
    assert "/primary_ind/1/" in service.paths[0] and f"/doc_ctrl_num/{DOC}/" in service.paths[0]


def test_an_epa_assigned_code_is_flagged_as_possibly_generic() -> None:
    """The real case: a 1988 submission whose code EPA assigned from a crosswalk."""
    row = _row("339999", source="ASSIGNED")
    row["method"] = "COMMERCIAL"
    result = Service([row]).run("1300145107633")
    assert result["naics_code"] == "339999"
    assert result["naics_title"] == "All Other Miscellaneous Manufacturing"
    assert result["code_origin"] == "assigned"
    assert "EPA assigned NAICS code 339999" in result["warnings"][0]
    assert "generic" in result["warnings"][0]


@pytest.mark.parametrize(
    ("source", "origin"),
    [
        ("Reported", "reported"),
        ("reported", "reported"),
        ("ASSIGNED", "assigned"),
        ("assigned", "assigned"),
        ("Other", None),
        (None, None),
        ("", None),
    ],
)
def test_the_origin_follows_the_source_field(source: object, origin: str | None) -> None:
    assert Service([_row("324110", source=source)]).run()["code_origin"] == origin


def test_the_title_is_words_not_a_number() -> None:
    title = Service([_row("325412")]).run()["naics_title"]
    assert title == "Pharmaceutical Preparation Manufacturing"
    assert title is not None and not title.isdigit()


def test_integer_control_numbers_are_accepted() -> None:
    assert Service([_row("324110")]).run(1313000000001)["naics_code"] == "324110"
    assert Service([_row("324110")]).run(f" {DOC} ")["naics_code"] == "324110"


def test_integer_naics_codes_in_the_response_are_accepted() -> None:
    assert Service([_row(324110)]).run()["naics_code"] == "324110"


def test_the_lowest_sequence_wins_when_a_submission_lists_several_primary_rows() -> None:
    result = Service([_row("325412", sequence=2), _row("324110", sequence=1)]).run()
    assert result["naics_code"] == "324110"
    assert "2 primary NAICS codes" in result["warnings"][0]


def test_a_sequence_tie_goes_to_the_smaller_code() -> None:
    assert Service([_row("325412"), _row("324110")]).run()["naics_code"] == "324110"


def test_a_missing_sequence_ranks_last() -> None:
    result = Service([_row("324110", sequence=None), _row("325412", sequence=3)]).run()
    assert result["naics_code"] == "325412"


def test_one_code_repeated_in_several_rows_is_not_several_codes() -> None:
    assert Service([_row("324110"), _row("324110", sequence=2)]).run()["warnings"] == []


@pytest.mark.parametrize("flag", ["0", "", None, 0, "2"])
def test_a_non_primary_row_is_never_the_industry(flag: object) -> None:
    result = Service([_row("324110", primary=flag)]).run()
    assert result["naics_code"] is None
    assert "no primary NAICS code" in result["warnings"][0]


def test_an_integer_primary_flag_means_the_same_as_the_string() -> None:
    assert Service([_row("324110", primary=1)]).run()["naics_code"] == "324110"


def test_a_placeholder_code_is_not_an_industry() -> None:
    result = Service([_row("999999")]).run()
    assert result["naics_code"] is None and result["naics_title"] is None
    assert "999999" in result["warnings"][0] and "placeholder" in result["warnings"][0]


def test_a_placeholder_is_ignored_when_a_real_primary_code_is_listed() -> None:
    result = Service([_row("999999", sequence=1), _row("324110", sequence=2)]).run()
    assert result["naics_code"] == "324110" and result["warnings"] == []


def test_a_missing_title_keeps_the_code_and_says_the_title_is_needed() -> None:
    result = Service([_row("311111")]).run()
    assert result["naics_code"] == "311111" and result["naics_title"] is None
    assert result["source"] == SOURCE
    assert "title is needed" in result["warnings"][0]


def test_a_blank_title_counts_as_missing() -> None:
    assert Service([_row("324110")], titles={"324110": "   "}).run()["naics_title"] is None


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"naics_code": "324110"}],
        [_row(None)],
        [_row("")],
        [_row("32-411")],
        [_row("3x4110")],
        [_row(True)],
    ],
)
def test_no_usable_primary_row_gives_nulls_and_a_warning(rows: list[dict[str, object]]) -> None:
    assert Service(rows).run() == FacilityIndustry(
        naics_code=None,
        naics_title=None,
        code_origin=None,
        source=None,
        warnings=[f"TRI reports no primary NAICS code for submission {DOC}"],
    )


@pytest.mark.parametrize("doc", ["", "   ", "abc", "13-13", "1.5", -1, True])
def test_an_invalid_control_number_makes_no_request(doc: str | int) -> None:
    service = Service([_row("324110")])
    result = service.run(doc)
    assert result["naics_code"] is None and "invalid" in result["warnings"][0]
    assert service.requests == []


@pytest.mark.parametrize("body", [{"error": "Query failed"}, "text", 5, [1, 2]])
def test_an_unexpected_answer_is_a_warning_not_an_exception(body: object) -> None:
    result = Service(body).run()
    assert result["naics_code"] is None
    assert "could not be looked up" in result["warnings"][0]


def test_a_failing_service_is_a_warning_not_an_exception() -> None:
    result = Service([], status=500).run()
    assert result["naics_code"] is None
    assert "could not be looked up" in result["warnings"][0]


def test_the_titles_are_read_from_the_reference_table_not_made_up() -> None:
    result = Service([_row("324110")], titles={"324110": "Whatever The Table Says"}).run()
    assert result["naics_title"] == "Whatever The Table Says"


# --- The local Census code lists come first --------------------------------------------------


def test_a_listed_code_is_titled_from_the_local_lists_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(naics, "naics_titles", LOCAL_TITLES)
    service = Service([_row("324110")], titles={"324110": "Whatever The Table Says"})
    result = service.run()
    assert result["naics_title"] == "Petroleum Refineries"
    assert result["warnings"] == []
    assert not any("REF_NAICS" in path for path in service.paths)


def test_a_code_the_lists_lack_is_asked_of_the_reference_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(naics, "naics_titles", LOCAL_TITLES)
    service = Service([_row("123456")], titles={"123456": "From The Reference Table"})
    assert service.run()["naics_title"] == "From The Reference Table"
    assert any("REF_NAICS" in path for path in service.paths)
