"""Typed loader for ``[ui.air_release]``: how a facility's total annual air release is computed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from config.parsing import require_str, subtable

_NAME = "ui.air_release"
REASONS = ("none_reported", "unit_not_convertible")


@dataclass(frozen=True)
class AirReleaseRules:
    """How the total is computed.

    Attributes:
        target_unit: Mass unit the stack release is converted to (Pint spelling, e.g. ``"kg"``);
            the total is per year because the inventory reports annual quantities.
        aliases: Reported unit spelling -> Pint-parsable unit (from ``[units.aliases]``).
        reasons: ``none_reported`` / ``unit_not_convertible`` -> why a facility has no total.
    """

    target_unit: str
    aliases: Mapping[str, str]
    reasons: Mapping[str, str]


def parse_air_release(
    ui_table: dict[str, object],
    aliases: Mapping[str, str],
) -> AirReleaseRules:
    """Validate the ``air_release`` table of an already-read ``[ui]`` table.

    Raises:
        ValueError: If a key is missing or empty; the message names it.
    """
    table = subtable(ui_table, "air_release", "ui")
    reasons = subtable(table, "reasons", _NAME)
    return AirReleaseRules(
        target_unit=require_str(table, "target_unit", _NAME).strip(),
        aliases=MappingProxyType(dict(aliases)),
        reasons=MappingProxyType(
            {key: require_str(reasons, key, f"{_NAME}.reasons").strip() for key in REASONS},
        ),
    )
