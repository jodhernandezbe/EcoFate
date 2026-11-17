"""Guards for the citation metadata: CITATION.cff is the one source Zenodo and GitHub read.

Each rule is a checker that returns its problems (empty when the data is fine), so the real file
is checked once and every rule is also shown to reject an altered copy.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = (
    "title",
    "type",
    "authors",
    "abstract",
    "repository-code",
    "license",
    "version",
    "date-released",
)
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
ORCID = re.compile(r"^https://orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
# First lines of LICENSE -> SPDX identifier; an unknown licence fails until it is added here.
LICENCES = {("Apache License", "Version 2.0"): "Apache-2.0"}


def _citation(root: Path = ROOT) -> dict[str, Any]:
    data = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    assert isinstance(data, dict), "CITATION.cff must be a YAML mapping"
    return cast(dict[str, Any], data)


def _package_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _spdx_of(licence_text: str) -> str | None:
    head = licence_text[:400]
    for markers, spdx in LICENCES.items():
        if all(marker in head for marker in markers):
            return spdx
    return None


# --- the rules ------------------------------------------------------------------------------


def missing_fields(data: dict[str, Any]) -> list[str]:
    """Required fields that are absent or empty, plus authors without both names."""
    problems = [name for name in REQUIRED if not data.get(name)]
    if data.get("type") and data["type"] != "software":
        problems.append("type (must be software)")
    for index, author in enumerate(data.get("authors") or []):
        for part in ("family-names", "given-names"):
            if not (isinstance(author, dict) and author.get(part)):
                problems.append(f"authors[{index}].{part}")
    return problems


def version_problems(data: dict[str, Any], package_version: str) -> list[str]:
    cited = str(data.get("version", ""))
    return (
        []
        if cited == package_version
        else [f"CITATION.cff {cited!r} != pyproject.toml {package_version!r}"]
    )


def licence_problems(data: dict[str, Any], licence_text: str) -> list[str]:
    spdx = _spdx_of(licence_text)
    if spdx is None:
        return ["LICENSE header not recognised; add it to LICENCES in tests/test_citation.py"]
    return [] if data.get("license") == spdx else [f"license {data.get('license')!r} != {spdx!r}"]


def date_problems(data: dict[str, Any], today: dt.date) -> list[str]:
    raw = data.get("date-released")
    try:
        released = raw if isinstance(raw, dt.date) else dt.date.fromisoformat(str(raw))
    except ValueError:
        return [f"date-released {raw!r} is not a YYYY-MM-DD date"]
    return [] if released <= today else [f"date-released {released} is after today"]


def identifier_problems(data: dict[str, Any]) -> list[str]:
    """A DOI, and each author's ORCID, when present, must be well formed."""
    problems: list[str] = []
    doi = data.get("doi")
    if doi is not None and not DOI.match(str(doi)):
        problems.append(f"doi {doi!r} is not 10.<digits>/<suffix>")
    for index, author in enumerate(data.get("authors") or []):
        orcid: object = (
            cast(dict[str, Any], author).get("orcid") if isinstance(author, dict) else None
        )
        if orcid is not None and not ORCID.match(str(orcid)):
            problems.append(f"authors[{index}].orcid {orcid!r} is not an ORCID URL")
    return problems


def second_source_problems(root: Path) -> list[str]:
    if (root / ".zenodo.json").exists():
        return [".zenodo.json found: CITATION.cff is the one source of archive metadata"]
    return []


# --- the real file --------------------------------------------------------------------------


def test_citation_is_complete_consistent_and_the_only_source() -> None:
    data = _citation()
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    problems = [
        *missing_fields(data),
        *version_problems(data, _package_version()),
        *licence_problems(data, licence),
        *date_problems(data, dt.date.today()),
        *identifier_problems(data),
        *second_source_problems(ROOT),
    ]
    assert problems == []


# --- each rule rejects a bad copy -------------------------------------------------------------


def _altered(**changes: object) -> dict[str, Any]:
    data = copy.deepcopy(_citation())
    for key, value in changes.items():
        name = key.replace("_", "-")
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    return data


@pytest.mark.parametrize(
    "field",
    ["abstract", "title", "version", "date_released", "repository_code"],
)
def test_a_missing_field_is_named(field: str) -> None:
    assert field.replace("_", "-") in missing_fields(_altered(**{field: None}))


def test_an_author_without_a_given_name_is_named() -> None:
    data = _altered(authors=[{"family-names": "Doe"}])
    assert missing_fields(data) == ["authors[0].given-names"]


def test_a_type_other_than_software_is_rejected() -> None:
    assert missing_fields(_altered(type="dataset")) == ["type (must be software)"]


def test_a_version_bumped_in_one_file_only_names_both() -> None:
    (problem,) = version_problems(_altered(version="0.1.0"), "0.2.0")
    assert "'0.1.0'" in problem and "'0.2.0'" in problem


def test_a_licence_that_does_not_match_license_is_rejected() -> None:
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert licence_problems(_altered(license="MIT"), licence)


def test_an_unrecognised_licence_text_fails_closed() -> None:
    assert licence_problems(_altered(), "Some other licence text")


@pytest.mark.parametrize("value", ["2026-02-30", "yesterday", "17/11/2026"])
def test_a_date_that_is_not_a_calendar_date_is_rejected(value: str) -> None:
    assert date_problems(_altered(date_released=value), dt.date(2026, 11, 17))


def test_a_release_date_in_the_future_is_rejected() -> None:
    assert date_problems(_altered(date_released="2026-11-18"), dt.date(2026, 11, 17))


def test_today_and_yaml_dates_are_accepted() -> None:
    assert date_problems(_altered(date_released=dt.date(2026, 11, 17)), dt.date(2026, 11, 17)) == []


@pytest.mark.parametrize("doi", ["10.5281/zenodo.123", "10.1000/xyz.abc"])
def test_a_well_formed_doi_is_accepted(doi: str) -> None:
    assert identifier_problems(_altered(doi=doi)) == []


@pytest.mark.parametrize("doi", ["zenodo.123", "https://doi.org/10.5281/zenodo.123", "10.52/x"])
def test_a_malformed_doi_is_rejected(doi: str) -> None:
    assert identifier_problems(_altered(doi=doi))


def test_a_malformed_orcid_is_rejected_and_a_good_one_accepted() -> None:
    good = [
        {
            "family-names": "Doe",
            "given-names": "Jo",
            "orcid": "https://orcid.org/0000-0002-1825-009X",
        },
    ]
    bad = [{"family-names": "Doe", "given-names": "Jo", "orcid": "0000-0002-1825-0097"}]
    assert identifier_problems(_altered(authors=good)) == []
    assert identifier_problems(_altered(authors=bad))


def test_a_zenodo_json_beside_the_citation_is_rejected(tmp_path: Path) -> None:
    assert second_source_problems(tmp_path) == []
    (tmp_path / ".zenodo.json").write_text("{}", encoding="utf-8")
    assert second_source_problems(tmp_path)
