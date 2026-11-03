"""Tests for models.exposure.inhalation (RAGS Part F: exposure concentration, doses, risk)."""

from __future__ import annotations

import math

import pytest

from models.exposure.inhalation import (
    annual_from_one_hour,
    cancer_risk_from_iur,
    doses_by_age_band,
    exposure_concentration,
    hazard_quotient_from_rfc,
    highest_dose_band,
)


def test_annual_factor() -> None:
    assert annual_from_one_hour(100.0, 0.08) == pytest.approx(8.0)
    assert annual_from_one_hour(0.0, 0.08) == 0.0
    assert annual_from_one_hour(100.0, 1.0) == 100.0


@pytest.mark.parametrize("factor", [0.0, -0.1, 1.01, math.nan, True])
def test_annual_factor_out_of_range(factor: float) -> None:
    with pytest.raises(ValueError, match="annual_factor"):
        annual_from_one_hour(100.0, factor)


def test_negative_concentration_is_rejected() -> None:
    with pytest.raises(ValueError, match="concentration_1h"):
        annual_from_one_hour(-1.0, 0.08)


def test_continuous_exposure_equals_the_air_concentration() -> None:
    assert exposure_concentration(10.0, 24.0, 365.0, 26.0, 26.0) == pytest.approx(10.0)


def test_resident_non_cancer_exposure_concentration() -> None:
    assert exposure_concentration(10.0, 24.0, 350.0, 26.0, 26.0) == pytest.approx(
        10.0 * 350.0 / 365.0,
    )


def test_cancer_averaging_over_a_lifetime() -> None:
    non_cancer = exposure_concentration(10.0, 24.0, 350.0, 26.0, 26.0)
    cancer = exposure_concentration(10.0, 24.0, 350.0, 26.0, 70.0)
    assert cancer == pytest.approx(non_cancer * 26.0 / 70.0)


def test_part_time_exposure() -> None:
    assert exposure_concentration(10.0, 8.0, 365.0, 1.0, 1.0) == pytest.approx(10.0 / 3.0)


@pytest.mark.parametrize(
    "args",
    [
        (10.0, 25.0, 350.0, 26.0, 26.0),
        (10.0, 24.0, 366.0, 26.0, 26.0),
        (10.0, -1.0, 350.0, 26.0, 26.0),
        (10.0, 24.0, 350.0, 0.0, 26.0),
        (10.0, 24.0, 350.0, 26.0, 0.0),
        (-1.0, 24.0, 350.0, 26.0, 26.0),
        (math.nan, 24.0, 350.0, 26.0, 26.0),
    ],
)
def test_exposure_concentration_rejects_impossible_input(
    args: tuple[float, float, float, float, float],
) -> None:
    with pytest.raises(ValueError):
        exposure_concentration(*args)


def test_hazard_quotient_converts_the_rfc_to_micrograms() -> None:
    assert hazard_quotient_from_rfc(10.0, 0.02) == pytest.approx(0.5)


def test_hazard_quotient_zero_exposure() -> None:
    assert hazard_quotient_from_rfc(0.0, 0.02) == 0.0


@pytest.mark.parametrize("rfc", [0.0, -1.0, math.nan])
def test_hazard_quotient_rejects_a_bad_rfc(rfc: float) -> None:
    with pytest.raises(ValueError, match="rfc"):
        hazard_quotient_from_rfc(10.0, rfc)


def test_cancer_risk() -> None:
    assert cancer_risk_from_iur(10.0, 1e-6) == pytest.approx(1e-5)
    assert cancer_risk_from_iur(10.0, 0.0) == 0.0


@pytest.mark.parametrize("iur", [-1e-6, math.nan, math.inf])
def test_cancer_risk_rejects_a_bad_iur(iur: float) -> None:
    with pytest.raises(ValueError):
        cancer_risk_from_iur(10.0, iur)


RATES = {"0-4": 8.0, "5-17": 10.1, "18-64": 20.0, "65+": 14.2}
WEIGHTS = {"0-4": 11.4, "5-17": 18.6, "18-64": 80.0, "65+": 80.0}


def test_dose_hand_computed() -> None:
    # 10 ug/m3 = 0.01 mg/m3; ADD = 0.01 * 20 * 350 * 26 / (80 * 26 * 365) = 70 / 29200
    doses = doses_by_age_band(10.0, {"18-64": 100.0}, RATES, WEIGHTS, 350.0, 26.0)
    assert doses == {"18-64": pytest.approx(70.0 / 29200.0)}


def test_children_have_the_higher_dose() -> None:
    doses = doses_by_age_band(10.0, {"0-4": 5.0, "18-64": 95.0}, RATES, WEIGHTS, 350.0, 26.0)
    assert doses["0-4"] > doses["18-64"]
    assert doses["0-4"] == pytest.approx(0.01 * 8.0 * 350.0 / (11.4 * 365.0))
    assert highest_dose_band(doses) == ("0-4", doses["0-4"])


def test_absent_bands_are_omitted() -> None:
    doses = doses_by_age_band(
        10.0,
        {"0-4": 0.0, "5-17": 0.0, "18-64": 60.0, "65+": 40.0},
        RATES,
        WEIGHTS,
        350.0,
        26.0,
    )
    assert set(doses) == {"18-64", "65+"}


def test_no_band_present_gives_no_doses() -> None:
    assert doses_by_age_band(10.0, {"0-4": 0.0}, RATES, WEIGHTS, 350.0, 26.0) == {}
    assert highest_dose_band({}) is None


def test_dose_is_linear_in_concentration() -> None:
    a = doses_by_age_band(10.0, {"18-64": 100.0}, RATES, WEIGHTS, 350.0, 26.0)["18-64"]
    b = doses_by_age_band(20.0, {"18-64": 100.0}, RATES, WEIGHTS, 350.0, 26.0)["18-64"]
    assert b == pytest.approx(2 * a)


def test_highest_band_is_deterministic_on_ties() -> None:
    assert highest_dose_band({"5-17": 1.0, "18-64": 1.0}) == ("5-17", 1.0)


@pytest.mark.parametrize(
    ("shares", "match"),
    [({"18-64": -1.0}, "share"), ({"18-64": math.nan}, "share"), ({"teen": 10.0}, "teen")],
)
def test_dose_rejects_bad_bands(shares: dict[str, float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        doses_by_age_band(10.0, shares, RATES, WEIGHTS, 350.0, 26.0)


def test_dose_rejects_bad_scalars() -> None:
    with pytest.raises(ValueError, match="concentration"):
        doses_by_age_band(-1.0, {"18-64": 100.0}, RATES, WEIGHTS, 350.0, 26.0)
    with pytest.raises(ValueError, match="exposure_frequency"):
        doses_by_age_band(10.0, {"18-64": 100.0}, RATES, WEIGHTS, 400.0, 26.0)
