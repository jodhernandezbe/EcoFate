"""Build the factors of a scenario: a value a tool returned, or the reason there is none."""

from __future__ import annotations

from typing import Literal

from commons.bands import Band, band_of
from config.risk_bands import get_risk_bands
from config.scenario import get_scenario_settings
from tools.schemas import ScenarioFactor

NOT_REPORTED = "not reported by any source"


def banded(quantity: Literal["hq", "cancer_risk", "oel_ratio"], value: float) -> tuple[Band, float]:
    """The band of one value alone and the upper boundary of its quantity (the benchmark)."""
    lower, upper = get_risk_bands().boundaries(quantity)
    return band_of(value, lower, upper), upper


def factor(
    key: str,
    value: float | str | None,
    *,
    source: str | None = None,
    reason: str | None = None,
    unit: str | None = None,
) -> ScenarioFactor:
    """One factor, shown as configured (group, label, unit).

    Args:
        key: The factor's key in ``[scenario.factors]``.
        value: What a tool returned; None when nothing did.
        source: Where the value came from, when a tool said.
        reason: Why there is no value; a generic reason is given when none is passed.
        unit: A unit that replaces the configured one (e.g. the unit a release was reported in).

    Raises:
        KeyError: If the key is not configured (a mistake in code, not in data).
    """
    spec = get_scenario_settings().factors[key]
    missing = value is None
    return ScenarioFactor(
        key=key,
        group=spec.group,
        label=spec.label,
        value=value,
        unit="" if missing else (spec.unit if unit is None else unit),
        source=None if missing else source,
        reason=(reason or NOT_REPORTED) if missing else None,
    )
