"""Tests for the TRI and emissions settings loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from commons.units import convert
from config.loader import (
    TRI_FIELD_KEYS,
    TriSettings,
    get_unit_settings,
    load_emissions_settings,
    load_tri_settings,
)

TRI = """
[tri]
release_path = "/r/{casrn}/{medium}/{after_year}/{start}:{end}"
media = ["AIR STACK", " WATER "]
fugitive_medium = " AIR FUG "
page_size = 50
recent_years = 7
publication_lag_years = 1
max_listed = 5
max_worker_only = 4
max_pages = 3
east_longitude_states = ["GU"]
facility_id_fields = ["reg", "frs"]

[tri.fields]
medium = "m"
year = "y"
doc_ctrl_num = "dc"
quantity = "q"
unit = "u"
facility_name = "n"
latitude = "la"
longitude = "lo"
address = "a"
city = "c"
county = "co"
state = "s"
zip_code = "z"
naics_code = "nc"
naics_primary = "np"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _tri(tmp_path: Path, text: str = TRI) -> TriSettings:
    return load_tri_settings(_write(tmp_path, text))


def test_tri_explicit_values(tmp_path: Path) -> None:
    settings = _tri(tmp_path)
    assert settings.release_path == "/r/{casrn}/{medium}/{after_year}/{start}:{end}"
    assert settings.recent_years == 7
    assert settings.max_listed == 5
    assert settings.max_worker_only == 4
    assert settings.fields["doc_ctrl_num"] == "dc"
    assert settings.media == ("AIR STACK", "WATER")
    assert settings.fugitive_medium == "AIR FUG"
    assert (settings.page_size, settings.max_pages) == (50, 3)
    assert settings.east_longitude_states == ("GU",)
    assert settings.facility_id_fields == ("reg", "frs")
    assert settings.fields["quantity"] == "q"


def test_tri_default_file_loads() -> None:
    settings = load_tri_settings()
    assert settings.media == ("AIR STACK",)
    assert settings.fugitive_medium == "AIR FUG"
    assert set(settings.fields) == set(TRI_FIELD_KEYS)
    assert settings.facility_id_fields[0] == "epa_registry_id"
    assert settings.page_size > 0
    assert settings.max_pages > 0
    assert settings.recent_years == 2
    assert settings.publication_lag_years == 1
    assert settings.max_listed == 25
    assert settings.max_worker_only == 25
    for slot in ("{casrn}", "{medium}", "{after_year}", "{start}", "{end}"):
        assert slot in settings.release_path


def test_tri_fields_are_read_only(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        _tri(tmp_path).fields["quantity"] = "x"  # type: ignore[index]


@pytest.mark.parametrize("slot", ["{casrn}", "{medium}", "{after_year}", "{start}", "{end}"])
def test_tri_path_needs_each_placeholder(tmp_path: Path, slot: str) -> None:
    with pytest.raises(ValueError, match="tri.release_path"):
        _tri(tmp_path, TRI.replace(slot, "x", 1))


@pytest.mark.parametrize(
    ("line", "bad", "key"),
    [
        ("recent_years = 7", "recent_years = 0", "recent_years"),
        ("recent_years = 7", "recent_years = 1.5", "recent_years"),
        ("recent_years = 7", "recent_years = true", "recent_years"),
        ("recent_years = 7", "", "recent_years"),
        ("publication_lag_years = 1", "publication_lag_years = -1", "publication_lag_years"),
        ("publication_lag_years = 1", "publication_lag_years = true", "publication_lag_years"),
        ("publication_lag_years = 1", "", "publication_lag_years"),
        ("max_listed = 5", "max_listed = 0", "max_listed"),
        ("max_listed = 5", "max_listed = true", "max_listed"),
        ("max_listed = 5", "", "max_listed"),
        ("max_worker_only = 4", "max_worker_only = 0", "max_worker_only"),
        ("max_worker_only = 4", "max_worker_only = true", "max_worker_only"),
        ("max_worker_only = 4", "", "max_worker_only"),
        ("page_size = 50", "page_size = 0", "page_size"),
        ("page_size = 50", "page_size = 1.5", "page_size"),
        ("page_size = 50", "page_size = true", "page_size"),
        ("max_pages = 3", "max_pages = 0", "max_pages"),
        ('media = ["AIR STACK", " WATER "]', "media = []", "media"),
        ('media = ["AIR STACK", " WATER "]', 'media = [""]', "media"),
        ('fugitive_medium = " AIR FUG "', "", "fugitive_medium"),
        ('fugitive_medium = " AIR FUG "', 'fugitive_medium = ""', "fugitive_medium"),
        ('fugitive_medium = " AIR FUG "', 'fugitive_medium = "WATER"', "fugitive_medium"),
        ('facility_id_fields = ["reg", "frs"]', "facility_id_fields = []", "facility_id_fields"),
        ('east_longitude_states = ["GU"]', "east_longitude_states = [1]", "east_longitude_states"),
    ],
)
def test_tri_invalid_values_name_the_key(tmp_path: Path, line: str, bad: str, key: str) -> None:
    with pytest.raises(ValueError, match=f"tri.{key}"):
        _tri(tmp_path, TRI.replace(line, bad))


def test_tri_no_east_states_is_allowed(tmp_path: Path) -> None:
    text = TRI.replace('east_longitude_states = ["GU"]', "east_longitude_states = []")
    assert _tri(tmp_path, text).east_longitude_states == ()


def test_tri_field_missing_and_table_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tri.fields.longitude"):
        _tri(tmp_path, TRI.replace('longitude = "lo"\n', ""))
    with pytest.raises(ValueError, match="tri.fields"):
        _tri(tmp_path, TRI.split("[tri.fields]")[0])


def test_tri_section_missing_and_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tri section"):
        _tri(tmp_path, "[other]\nx = 1\n")
    with pytest.raises(FileNotFoundError):
        load_tri_settings(tmp_path / "nope.toml")


def _emissions(tmp_path: Path, value: str) -> float:
    path = _write(tmp_path, f"[emissions]\noperating_hours_per_year = {value}\n")
    return load_emissions_settings(path).operating_hours_per_year


def test_emissions_default_is_continuous_operation() -> None:
    assert load_emissions_settings().operating_hours_per_year == 8760


def test_emissions_explicit_value(tmp_path: Path) -> None:
    assert _emissions(tmp_path, "2000") == 2000.0
    assert _emissions(tmp_path, "8784") == 8784.0


@pytest.mark.parametrize("value", ["0", "-5", "8785", "true", '"8760"'])
def test_emissions_invalid_hours(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="emissions.operating_hours_per_year"):
        _emissions(tmp_path, value)


def test_emissions_section_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="emissions section"):
        load_emissions_settings(_write(tmp_path, "[other]\nx = 1\n"))
    with pytest.raises(ValueError, match="operating_hours_per_year"):
        load_emissions_settings(_write(tmp_path, "[emissions]\n"))


def test_pounds_alias_converts_to_grams() -> None:
    aliases = get_unit_settings().aliases
    assert aliases["Pounds"] == "pound"
    assert convert(1.0, "Pounds", "g", aliases) == pytest.approx(453.59237)
    assert aliases["Grams"] == "gram"
    assert convert(10.0, "Grams", "kg", aliases) == pytest.approx(0.01)


def test_the_window_ends_with_the_newest_year_that_can_be_published(tmp_path: Path) -> None:
    settings = _tri(tmp_path)  # recent_years = 7, publication lag 1
    assert settings.after_year(2026) == 2018
    assert settings.first_year(2026) == 2019  # 2019..2025 are seven reporting years


def test_the_default_window_is_the_last_two_published_years() -> None:
    """TRI for 2025 is released by June 2026, so in 2026 the window is 2024 and 2025."""
    settings = load_tri_settings()
    assert settings.after_year(2026) == 2023
    assert settings.first_year(2026) == 2024
    assert range(settings.first_year(2026), 2026) == range(2024, 2026)
