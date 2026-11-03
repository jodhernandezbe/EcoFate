"""Tests for models.receptors.population."""

from __future__ import annotations

import math

import pytest

from models.receptors.population import AGE_BANDS, age_bands, scale_to_circle


def test_half_covered() -> None:
    assert scale_to_circle(1000.0, 5.0, 10.0) == 500.0


def test_circle_larger_than_the_land_returns_everyone() -> None:
    assert scale_to_circle(1000.0, 20.0, 10.0) == 1000.0


def test_exactly_covered() -> None:
    assert scale_to_circle(1000.0, 10.0, 10.0) == 1000.0


def test_unknown_land_area_returns_the_count_unscaled() -> None:
    assert scale_to_circle(1000.0, 5.0, 0.0) == 1000.0


def test_zero_count() -> None:
    assert scale_to_circle(0.0, 5.0, 10.0) == 0.0


@pytest.mark.parametrize(
    ("args", "name"),
    [
        ((-1.0, 5.0, 10.0), "count"),
        ((math.nan, 5.0, 10.0), "count"),
        ((1.0, 0.0, 10.0), "circle_area_m2"),
        ((1.0, -5.0, 10.0), "circle_area_m2"),
        ((1.0, math.inf, 10.0), "circle_area_m2"),
        ((1.0, 5.0, -1.0), "land_area_m2"),
        ((1.0, 5.0, math.nan), "land_area_m2"),
        ((True, 5.0, 10.0), "count"),
    ],
)
def test_scale_rejects_impossible_input(args: tuple[float, float, float], name: str) -> None:
    with pytest.raises(ValueError, match=name):
        scale_to_circle(*args)


def test_typical_age_bands() -> None:
    assert age_bands(1000.0, 100.0, 300.0, 200.0) == {
        "0-4": 10.0,
        "5-17": 20.0,
        "18-64": 50.0,
        "65+": 20.0,
    }


def test_bands_use_the_documented_names_in_order() -> None:
    assert tuple(age_bands(10.0, 1.0, 3.0, 2.0)) == ("0-4", "5-17", "18-64", "65+") == AGE_BANDS


def test_bands_sum_to_100_even_when_rounding() -> None:
    bands = age_bands(3.0, 1.0, 2.0, 1.0)  # thirds
    assert sum(bands.values()) == pytest.approx(100.0, abs=0.01)
    assert all(v >= 0 for v in bands.values())


def test_everyone_over_65() -> None:
    assert age_bands(10.0, 0.0, 0.0, 10.0) == {"0-4": 0.0, "5-17": 0.0, "18-64": 0.0, "65+": 100.0}


def test_everyone_under_five() -> None:
    assert age_bands(10.0, 10.0, 10.0, 0.0) == {"0-4": 100.0, "5-17": 0.0, "18-64": 0.0, "65+": 0.0}


def test_large_counts() -> None:
    bands = age_bands(332_387_540.0, 18_950_000.0, 54_850_000.0, 55_840_000.0)
    assert sum(bands.values()) == pytest.approx(100.0, abs=0.01)


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ((0.0, 0.0, 0.0, 0.0), "total"),
        ((-5.0, 0.0, 0.0, 0.0), "total"),
        ((math.nan, 0.0, 0.0, 0.0), "total"),
        ((10.0, -1.0, 3.0, 2.0), "under_5"),
        ((10.0, 1.0, -3.0, 2.0), "under_18"),
        ((10.0, 1.0, 3.0, -2.0), "over_65"),
        ((10.0, 1.0, math.inf, 2.0), "under_18"),
        ((10.0, 4.0, 3.0, 2.0), "under_5 must not exceed under_18"),
        ((10.0, 1.0, 9.0, 2.0), "under_18 plus over_65"),
        ((10.0, 1.0, 3.0, 11.0), "under_18 plus over_65"),
        ((True, 0.0, 0.0, 0.0), "total"),
    ],
)
def test_bands_reject_impossible_counts(
    args: tuple[float, float, float, float],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        age_bands(*args)
