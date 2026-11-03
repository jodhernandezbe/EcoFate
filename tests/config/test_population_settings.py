"""Tests for the ``[population]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.population import (
    ACS_VARIABLES,
    AGE_BANDS,
    TRACT_FIELDS,
    PopulationSettings,
    load_population_settings,
)

TEXT = """
[population]
tract_url = "https://tiger.test/query"
acs_base_url = "https://acs.test/"
acs_path = "/data/{year}/profile"
acs_year = 2020
api_key_env_var = "MY_CENSUS_VAR"  # pragma: allowlist secret
default_radius_km = 2.0
min_radius_km = 0.5
max_radius_km = 10.0
max_counties = 4
max_tracts_listed = 7
delay_seconds = 0
timeout_seconds = 5
max_retries = 1
backoff_seconds = 0.5

[population.fields]
state = "S"
county = "C"
tract = "T"
land_area = "A"
latitude = "LAT"
longitude = "LON"

[population.variables]
total = "V1"
under_5 = "V2"
under_18 = "V3"
over_65 = "V4"

[population.screening_default]
residents_per_km2 = 100.0

[population.screening_default.age_distribution]
"0-4" = 10.0
"5-17" = 20.0
"18-64" = 50.0
"65+" = 20.0
"""


def _load(tmp_path: Path, text: str = TEXT) -> PopulationSettings:
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_population_settings(path)


def test_explicit_values(tmp_path: Path) -> None:
    s = _load(tmp_path)
    assert s.tract_url == "https://tiger.test/query"
    assert s.acs_url == "https://acs.test/data/2020/profile"
    assert (s.acs_year, s.api_key_env_var) == (2020, "MY_CENSUS_VAR")
    assert (s.min_radius_km, s.default_radius_km, s.max_radius_km) == (0.5, 2.0, 10.0)
    assert s.max_counties == 4
    assert s.max_tracts_listed == 7
    assert (s.policy.delay_seconds, s.policy.timeout_seconds) == (0, 5)
    assert (s.policy.max_retries, s.policy.backoff_seconds) == (1, 0.5)
    assert s.fields["land_area"] == "A"
    assert (s.fields["latitude"], s.fields["longitude"]) == ("LAT", "LON")
    assert s.variables["over_65"] == "V4"
    assert s.screening_default.residents_per_km2 == 100.0
    assert dict(s.screening_default.age_distribution) == {
        "0-4": 10.0,
        "5-17": 20.0,
        "18-64": 50.0,
        "65+": 20.0,
    }


def test_default_file_loads() -> None:
    s = load_population_settings()
    assert s.acs_url.endswith("/acs5/profile")
    assert s.api_key_env_var == "CENSUS_API_KEY"  # pragma: allowlist secret
    assert set(s.fields) == set(TRACT_FIELDS)
    assert set(s.variables) == set(ACS_VARIABLES)
    assert set(s.screening_default.age_distribution) == set(AGE_BANDS)
    assert abs(sum(s.screening_default.age_distribution.values()) - 100.0) <= 0.5
    assert s.min_radius_km <= s.default_radius_km <= s.max_radius_km


def test_the_settings_hold_a_variable_name_never_a_key(tmp_path: Path) -> None:
    assert "MY_CENSUS_VAR" in repr(_load(tmp_path))


def test_tables_are_read_only(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        _load(tmp_path).variables["total"] = "X"  # type: ignore[index]
    with pytest.raises(TypeError):
        _load(tmp_path).screening_default.age_distribution["0-4"] = 1.0  # type: ignore[index]


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ('tract_url = "https://tiger.test/query"', 'tract_url = ""', "population.tract_url"),
        ('acs_base_url = "https://acs.test/"', "", "population.acs_base_url"),
        ('acs_path = "/data/{year}/profile"', 'acs_path = "/data/profile"', "acs_path"),
        ('acs_path = "/data/{year}/profile"', 'acs_path = "data/{year}"', "acs_path"),
        ("acs_year = 2020", "acs_year = 2020.5", "population.acs_year"),
        ("acs_year = 2020", "acs_year = true", "population.acs_year"),
        ("acs_year = 2020", "acs_year = 1999", "population.acs_year"),
        (
            'api_key_env_var = "MY_CENSUS_VAR"',  # pragma: allowlist secret
            'api_key_env_var = ""',
            "api_key_env_var",
        ),
        ("default_radius_km = 2.0", "default_radius_km = 0.1", "radii must satisfy"),
        ("default_radius_km = 2.0", "default_radius_km = 20.0", "radii must satisfy"),
        ("min_radius_km = 0.5", "min_radius_km = 0", "population.min_radius_km"),
        ("max_radius_km = 10.0", "max_radius_km = -1", "population.max_radius_km"),
        ("max_counties = 4", "max_counties = 0", "population.max_counties"),
        ("max_tracts_listed = 7", "max_tracts_listed = 0", "population.max_tracts_listed"),
        ("delay_seconds = 0", "delay_seconds = -1", "population.delay_seconds"),
        ("timeout_seconds = 5", "timeout_seconds = 0", "population.timeout_seconds"),
        ("max_retries = 1", "max_retries = 1.5", "population.max_retries"),
        ("backoff_seconds = 0.5", 'backoff_seconds = "x"', "population.backoff_seconds"),
        ('state = "S"', "", "population.fields.state"),
        ('land_area = "A"', 'land_area = ""', "population.fields.land_area"),
        ('latitude = "LAT"', 'latitude = ""', "population.fields.latitude"),
        ('tract = "T"', 'tracts = "T"', "unknown keys: tracts"),
        ('total = "V1"', "", "population.variables.total"),
        ('over_65 = "V4"', 'over_65 = ""', "population.variables.over_65"),
        ("residents_per_km2 = 100.0", "residents_per_km2 = -1", "residents_per_km2"),
        ("residents_per_km2 = 100.0", "", "residents_per_km2"),
        ('"65+" = 20.0', '"65+" = 25.0', "must sum to 100"),
        ('"65+" = 20.0', "", "age_distribution.65+"),
        ('"65+" = 20.0', '"65+" = -20.0', "age_distribution.65+"),
        ('"0-4" = 10.0', '"0-4" = 10.0\n"other" = 0.0', "unknown bands: other"),
    ],
)
def test_invalid_entries_name_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    assert old in TEXT
    with pytest.raises(ValueError, match=key.replace("+", r"\+")):
        _load(tmp_path, TEXT.replace(old, new, 1))


@pytest.mark.parametrize(
    "table",
    ["[population.fields]", "[population.variables]", "[population.screening_default]"],
)
def test_missing_subtable(tmp_path: Path, table: str) -> None:
    head, tail = TEXT.split(table, 1)
    rest = tail.split("\n[", 1)[1] if "\n[" in tail else ""
    if table == "[population.screening_default]":
        rest = ""
    with pytest.raises(ValueError, match=table.strip("[]")):
        _load(tmp_path, head + ("[" + rest if rest else ""))


def test_section_and_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="population section"):
        _load(tmp_path, "[other]\nx = 1\n")
    with pytest.raises(FileNotFoundError):
        load_population_settings(tmp_path / "absent.toml")
