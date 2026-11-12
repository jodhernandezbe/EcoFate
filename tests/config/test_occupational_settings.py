"""Tests for the ``[occupational]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.occupational import load_occupational_settings
from config.occupational_activities import AirSpeedParameters, Ap42Parameters

TEXT = """
[occupational]
shift_inhalation_m3 = 10.0
daily_inhalation_m3 = 20.0
worker_days_per_year = 250.0
tenure_years = 40.0
lifetime_years = 78.0
twa_hours = 8.0
temperature_k = 300.0
pressure_atm = 1.0
molar_volume_l_per_mol = 25.0
correction_factor = 1.0

[occupational.volatility]
low_torr = 0.01
high_torr = 30.0

[occupational.ventilation.indoor.baseline]
label = "Baseline"
rate_ft3_per_min = 3000.0
mixing_factor = 0.5

[occupational.ventilation.indoor.worst_case]
label = "Worst"
rate_ft3_per_min = 500.0
mixing_factor = 0.1

[occupational.ventilation.outdoor]
coefficient_ft3_per_min = 1000.0
baseline_air_speed_ft_per_min = 800.0
default_air_speed_ft_per_min = 400.0
baseline_mixing_factor = 0.5
worst_case_mixing_factor = 0.1

[occupational.two_zone]
near_field_length_m = 2.0
near_field_width_m = 2.0
near_field_height_m = 2.0
near_field_air_speed_m_per_h = 300.0

[occupational.two_zone.baseline]
volume_m3 = 1000.0
air_exchange_per_h = 10.0

[occupational.two_zone.worst_case]
volume_m3 = 100.0
air_exchange_per_h = 1.0

[occupational.activities.fill]
label = "Fill"
model = "ap42_loading"
setting = "indoor"
hours = 8.0
container_gallons = 50.0
fill_rate_per_hour = 10.0
saturation_factor = [0.5, 1.0]

[occupational.activities.sample]
label = "Sample"
model = "penetration"
setting = "indoor"
hours = 1.0
air_speed_ft_per_min = 90.0
diameter_cm = [2.0, 10.0]
proc = "9z"

[occupational.activities.clean]
label = "Clean"
model = "mass_transfer"
setting = "outdoor"
hours = 4.0
air_speed_ft_per_min = 400.0
diameter_cm = [90.0, 90.0]

[occupational.stage_activities]
Manufacturing = ["fill", "sample"]
"Industrial use" = ["clean"]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_loads_values(tmp_path: Path) -> None:
    s = load_occupational_settings(_write(tmp_path, TEXT))
    assert s.indoor.baseline.rate_ft3_per_min == 3000.0 and s.indoor.worst_case.mixing_factor == 0.1
    assert s.conditions.molar_volume_l_per_mol == 25.0 and s.volatility.high_torr == 30.0
    assert s.outdoor.default_air_speed_ft_per_min == 400.0
    assert s.two_zone.worst_case.air_exchange_per_h == 1.0
    assert s.stage_activities["Manufacturing"] == ("fill", "sample")


def test_activities_carry_their_model_parameters(tmp_path: Path) -> None:
    s = load_occupational_settings(_write(tmp_path, TEXT))
    fill, sample = s.activities["fill"], s.activities["sample"]
    assert isinstance(fill.parameters, Ap42Parameters) and fill.proc is None
    assert fill.parameters.saturation_factor.worst_case == 1.0
    assert isinstance(sample.parameters, AirSpeedParameters) and sample.proc == "9z"
    assert sample.parameters.diameter_cm.typical == 2.0 and sample.setting == "indoor"


def test_activities_are_read_only(tmp_path: Path) -> None:
    s = load_occupational_settings(_write(tmp_path, TEXT))
    with pytest.raises(TypeError):
        s.activities["x"] = s.activities["fill"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("mixing_factor = 0.5", "mixing_factor = 1.5", "mixing_factor"),
        ("rate_ft3_per_min = 3000.0", "rate_ft3_per_min = 0", "rate_ft3_per_min"),
        ("worker_days_per_year = 250.0", "worker_days_per_year = 400", "worker_days_per_year"),
        ("tenure_years = 40.0", "tenure_years = 90.0", "tenure_years"),
        ("shift_inhalation_m3 = 10.0", "shift_inhalation_m3 = 30.0", "shift_inhalation_m3"),
        ("twa_hours = 8.0", "twa_hours = true", "twa_hours"),
        ("correction_factor = 1.0", "correction_factor = 1.5", "correction_factor"),
        ("correction_factor = 1.0", "correction_factor = 0", "correction_factor"),
        ("temperature_k = 300.0\n", "", "temperature_k"),
        ("molar_volume_l_per_mol = 25.0", "molar_volume_l_per_mol = -1", "molar_volume"),
        ("low_torr = 0.01", "low_torr = 40.0", "low_torr"),
        ("baseline_mixing_factor = 0.5", "baseline_mixing_factor = 2", "baseline_mixing_factor"),
        ("coefficient_ft3_per_min = 1000.0", "coefficient_ft3_per_min = 0", "coefficient"),
        ("volume_m3 = 100.0", "volume_m3 = 0", "volume_m3"),
        ("near_field_height_m = 2.0", "near_field_height_m = -2.0", "near_field_height_m"),
    ],
)
def test_invalid_values_name_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_occupational_settings(_write(tmp_path, TEXT.replace(old, new, 1)))


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ('model = "ap42_loading"', 'model = "magic"', "model"),
        ('setting = "indoor"\nhours = 8.0', 'setting = "attic"\nhours = 8.0', "setting"),
        ("hours = 8.0", "hours = 30.0", "hours"),
        ("hours = 8.0", "hours = 0", "hours"),
        ("container_gallons = 50.0\n", "", "container_gallons"),
        ("fill_rate_per_hour = 10.0\n", "", "fill_rate_per_hour"),
        ("saturation_factor = [0.5, 1.0]", "saturation_factor = [0.5]", "saturation_factor"),
        ("saturation_factor = [0.5, 1.0]", "saturation_factor = [0.5, 1.5]", "saturation_factor"),
        ("saturation_factor = [0.5, 1.0]", "saturation_factor = [0.9, 0.5]", "saturation_factor"),
        ("saturation_factor = [0.5, 1.0]", "saturation_factor = [true, 1.0]", "saturation_factor"),
        ("air_speed_ft_per_min = 90.0", "air_speed_ft_per_min = 150.0", "air_speed_ft_per_min"),
        ("air_speed_ft_per_min = 400.0", "air_speed_ft_per_min = 50.0", "air_speed_ft_per_min"),
        ("air_speed_ft_per_min = 90.0\n", "", "air_speed_ft_per_min"),
        ("diameter_cm = [2.0, 10.0]", "diameter_cm = [10.0, 2.0]", "diameter_cm"),
        ("diameter_cm = [2.0, 10.0]", "diameter_cm = 2.0", "diameter_cm"),
        ('proc = "9z"', "proc = 9", "proc"),
    ],
)
def test_invalid_activity_names_the_activity(
    tmp_path: Path,
    old: str,
    new: str,
    fragment: str,
) -> None:
    activity = "fill" if "container" in old or "saturation" in old or "ap42" in old else None
    activity = activity or (
        "clean"
        if "400.0" in old
        else "sample"
        if "9z" in old or "diameter" in old or "90.0" in old
        else "fill"
    )
    block = f"[occupational.activities.{activity}]"
    head, _, rest = TEXT.partition(block)
    body, sep, tail = rest.partition("\n[")
    changed = head + block + body.replace(old, new, 1) + sep + tail
    assert changed != TEXT
    with pytest.raises(ValueError, match=rf"activities\.{activity}\.{fragment}"):
        load_occupational_settings(_write(tmp_path, changed))


def test_activities_table_must_not_be_empty(tmp_path: Path) -> None:
    head = TEXT.split("[occupational.activities.fill]")[0]
    text = head + "[occupational.activities]\n[occupational.stage_activities]\n"
    with pytest.raises(ValueError, match="activities"):
        load_occupational_settings(_write(tmp_path, text))


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ('Manufacturing = ["fill", "sample"]', 'Manufacturing = ["fill", "ghost"]', "ghost"),
        ('Manufacturing = ["fill", "sample"]', "Manufacturing = []", "Manufacturing"),
        ('Manufacturing = ["fill", "sample"]', 'Manufacturing = ["fill", 3]', "Manufacturing"),
        ('Manufacturing = ["fill", "sample"]', 'Disposal = ["fill"]', "Disposal"),
    ],
)
def test_invalid_stage_activities(tmp_path: Path, old: str, new: str, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        load_occupational_settings(_write(tmp_path, TEXT.replace(old, new, 1)))


def test_default_file_loads() -> None:
    settings = load_occupational_settings()
    assert settings.lifetime_years == 78.0
    assert len(settings.activities) == 9
    assert set(settings.stage_activities) == {"Manufacturing", "Processing", "Industrial use"}
