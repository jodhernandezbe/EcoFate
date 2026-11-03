"""Tests for the ``[exposure]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.exposure import AGE_BANDS, STABILITY_CLASSES, ExposureSettings, load_exposure_settings

TEXT = """
[exposure]
receptor_height_m = 1.5
annual_average_factor = 0.1
min_distance_m = 200.0
distance_segments = [
    { start = 100.0, end = 400.0, step = 100.0 },
    { start = 500.0, end = 1000.0, step = 250.0 },
]

[exposure.wind_speeds]
A = [1.0, 2.0]
B = [1.0]
C = [1.0]
D = [1.0, 5.0]
E = [1.0]
F = [1.0]

[exposure.wind_exponent]
A = 0.07
B = 0.07
C = 0.10
D = 0.15
E = 0.35
F = 0.55

[exposure.potential_temperature_gradient]
E = 0.02
F = 0.035

[exposure.factors]
exposure_time_hours_per_day = 20.0
exposure_frequency_days_per_year = 300.0
exposure_duration_years = 10.0
lifetime_years = 60.0

[exposure.age_bands."0-4"]
inhalation_rate_m3_per_day = 5.0
body_weight_kg = 10.0

[exposure.age_bands."5-17"]
inhalation_rate_m3_per_day = 6.0
body_weight_kg = 20.0

[exposure.age_bands."18-64"]
inhalation_rate_m3_per_day = 7.0
body_weight_kg = 70.0

[exposure.age_bands."65+"]
inhalation_rate_m3_per_day = 8.0
body_weight_kg = 80.0
"""


def _load(tmp_path: Path, text: str = TEXT) -> ExposureSettings:
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_exposure_settings(path)


def test_explicit_values(tmp_path: Path) -> None:
    s = _load(tmp_path)
    assert (s.receptor_height_m, s.annual_average_factor) == (1.5, 0.1)
    assert s.distances_m == (200.0, 300.0, 400.0, 500.0, 750.0, 1000.0)
    assert s.combinations == (
        ("A", 1.0),
        ("A", 2.0),
        ("B", 1.0),
        ("C", 1.0),
        ("D", 1.0),
        ("D", 5.0),
        ("E", 1.0),
        ("F", 1.0),
    )
    assert s.wind_exponent["F"] == 0.55
    assert dict(s.potential_temperature_gradient) == {"E": 0.02, "F": 0.035}
    assert s.factors.exposure_frequency_days_per_year == 300.0
    assert s.age_bands["65+"].body_weight_kg == 80.0


def test_default_file_is_screen3s_grid_truncated_at_10_km() -> None:
    s = load_exposure_settings()
    assert len(s.combinations) == 54
    assert [len(s.wind_speeds[c]) for c in STABILITY_CLASSES] == [5, 9, 11, 13, 9, 7]
    assert len(s.distances_m) == 44
    assert s.distances_m[:3] == (100.0, 200.0, 300.0)
    assert s.distances_m[29:32] == (3000.0, 3500.0, 4000.0)
    assert s.distances_m[-1] == 10000.0
    assert list(s.distances_m) == sorted(set(s.distances_m))


def test_default_file_has_the_verified_epa_values() -> None:
    s = load_exposure_settings()
    assert s.annual_average_factor == 0.08
    assert dict(s.wind_exponent) == {
        "A": 0.07,
        "B": 0.07,
        "C": 0.10,
        "D": 0.15,
        "E": 0.35,
        "F": 0.55,
    }
    assert dict(s.potential_temperature_gradient) == {"E": 0.02, "F": 0.035}
    f = s.factors
    assert (f.exposure_time_hours_per_day, f.exposure_frequency_days_per_year) == (24.0, 350.0)
    assert (f.exposure_duration_years, f.lifetime_years) == (26.0, 70.0)
    assert set(s.age_bands) == set(AGE_BANDS)
    assert s.age_bands["0-4"].inhalation_rate_m3_per_day == 8.0
    assert s.receptor_height_m == 0.0


def test_tables_are_read_only(tmp_path: Path) -> None:
    s = _load(tmp_path)
    with pytest.raises(TypeError):
        s.wind_exponent["A"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        s.age_bands["0-4"] = s.age_bands["65+"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("receptor_height_m = 1.5", "receptor_height_m = -1", "receptor_height_m"),
        ("annual_average_factor = 0.1", "annual_average_factor = 1.5", "annual_average_factor"),
        ("annual_average_factor = 0.1", "annual_average_factor = 0", "annual_average_factor"),
        ("annual_average_factor = 0.1", "annual_average_factor = true", "annual_average_factor"),
        ("min_distance_m = 200.0", "min_distance_m = 0", "min_distance_m"),
        ("min_distance_m = 200.0", "min_distance_m = 5000.0", "leaves no distance"),
        ("step = 100.0", "step = 0", "step"),
        ("end = 400.0", "end = 50.0", "end >= start"),
        ("start = 500.0", "start = 300.0", "ascending"),
        ("A = [1.0, 2.0]", "A = []", "exposure.wind_speeds.A"),
        ("A = [1.0, 2.0]", "A = [1.0, -2.0]", "exposure.wind_speeds.A"),
        ("A = [1.0, 2.0]", "A = [1.0, true]", "exposure.wind_speeds.A"),
        ("B = [1.0]\n", "", "exposure.wind_speeds.B"),
        ("A = 0.07", "A = -0.07", "exposure.wind_exponent"),
        ("F = 0.55", "G = 0.55", "unknown classes: G"),
        ("E = 0.02", "E = 0", "potential_temperature_gradient"),
        ("exposure_time_hours_per_day = 20.0", "exposure_time_hours_per_day = 25.0", "at most 24"),
        (
            "exposure_frequency_days_per_year = 300.0",
            "exposure_frequency_days_per_year = 366.0",
            "at most 365",
        ),
        (
            "exposure_duration_years = 10.0",
            "exposure_duration_years = 80.0",
            "must not exceed lifetime",
        ),
        ("lifetime_years = 60.0", "lifetime_years = 0", "lifetime_years"),
        (
            "inhalation_rate_m3_per_day = 5.0",
            "inhalation_rate_m3_per_day = 0",
            "inhalation_rate_m3_per_day",
        ),
        ("body_weight_kg = 10.0", "body_weight_kg = -10.0", "body_weight_kg"),
        ('[exposure.age_bands."65+"]', '[exposure.age_bands."90+"]', "unknown bands"),
    ],
)
def test_invalid_entries_name_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    assert old in TEXT
    with pytest.raises(ValueError, match=key):
        _load(tmp_path, TEXT.replace(old, new, 1))


def test_a_missing_band_is_named(tmp_path: Path) -> None:
    text = TEXT.split('[exposure.age_bands."65+"]')[0]
    with pytest.raises(ValueError, match="65"):
        _load(tmp_path, text)


@pytest.mark.parametrize(
    "table",
    ["[exposure.factors]", "[exposure.wind_exponent]", "[exposure.wind_speeds]"],
)
def test_a_missing_subtable_is_named(tmp_path: Path, table: str) -> None:
    head, tail = TEXT.split(table, 1)
    rest = tail.split("\n[", 1)[1]
    with pytest.raises(ValueError, match="exposure"):
        _load(tmp_path, head + "[" + rest)


def test_section_and_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exposure section"):
        _load(tmp_path, "[other]\nx = 1\n")
    with pytest.raises(FileNotFoundError):
        load_exposure_settings(tmp_path / "absent.toml")
