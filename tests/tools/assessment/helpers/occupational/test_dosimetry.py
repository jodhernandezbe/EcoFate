"""The worker band: limit ratio and cancer risk; the RfC hazard quotient only without a limit."""

from __future__ import annotations

from config.risk_bands import get_risk_bands
from tools.assessment.helpers.occupational.dosimetry import (
    band_of,
    cancer_risk_sets_band,
    empty_case,
)
from tools.schemas import WorkerCase


def test_with_a_limit_the_rfc_hazard_quotient_does_not_raise_the_band() -> None:
    assert band_of(ratio=0.38, hq=32.6, risk=None) == "moderate"


def test_with_a_limit_a_high_cancer_risk_still_raises_the_band() -> None:
    assert band_of(ratio=0.38, hq=None, risk=1e-3) == "high"


def test_the_higher_of_ratio_and_cancer_risk_wins() -> None:
    assert band_of(ratio=3.2, hq=None, risk=1e-5) == "high"


def test_without_a_limit_the_hazard_quotient_sets_the_band() -> None:
    assert band_of(ratio=None, hq=2.0, risk=None) == "high"


def test_without_a_limit_a_low_hazard_quotient_gives_low() -> None:
    assert band_of(ratio=None, hq=0.01, risk=None) == "low"


def test_nothing_computed_gives_no_band() -> None:
    assert band_of(ratio=None, hq=None, risk=None) is None


def _case(ratio: float | None, risk: float | None) -> WorkerCase:
    return {**empty_case(), "oel_ratio": ratio, "cancer_risk": risk}


def test_a_cancer_risk_above_the_ratio_band_sets_the_band() -> None:
    b = get_risk_bands()
    assert cancer_risk_sets_band(_case(b.oel_ratio_lower / 2, b.cancer_risk_upper))


def test_a_cancer_risk_in_the_ratio_band_does_not_set_it() -> None:
    b = get_risk_bands()
    assert not cancer_risk_sets_band(_case(b.oel_ratio_upper, b.cancer_risk_upper))


def test_without_a_ratio_or_a_risk_nothing_is_said() -> None:
    b = get_risk_bands()
    assert not cancer_risk_sets_band(_case(None, b.cancer_risk_upper))
    assert not cancer_risk_sets_band(_case(b.oel_ratio_lower / 2, None))
