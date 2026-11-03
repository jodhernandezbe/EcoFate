"""Live smoke test for FrsLocator against the EPA FRS best-pick lookup (no key needed).

Run with ``uv run pytest -m smoke``. The FRS IDs are real facilities: the first has no TRI
coordinates for the formaldehyde inventory (Puerto Rico), the others are in Rhode Island and Maine.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from config.efservice import get_efservice_settings
from config.frs_point import get_frs_point_settings
from tools.emissions.helpers.efservice import EfserviceClient
from tools.emissions.helpers.inventory.frs_point import FrsLocator

pytestmark = pytest.mark.smoke


def test_one_request_gives_the_coordinates_of_several_facilities() -> None:
    settings = get_frs_point_settings()
    with httpx.Client() as http:
        client = EfserviceClient(
            replace(get_efservice_settings(), base_url=settings.base_url),
            http,
        )
        found = FrsLocator(client, settings)(["110012141805", "110000313152", "110000314357"])
    assert set(found) == {"110012141805", "110000313152", "110000314357"}
    puerto_rico = found["110012141805"]
    assert 17.0 < puerto_rico.latitude < 19.0 and -68.0 < puerto_rico.longitude < -65.0
    assert 41.0 < found["110000313152"].latitude < 42.0
