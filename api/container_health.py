"""Container health check: ``python -m api.container_health`` exits 0 when the API is healthy.

It calls the health route on loopback with the site's own ``Host`` (``ui.origin``: the public
origin in production, ``host:port`` locally), so the origin guard stays strict and no domain is
written into the Dockerfile or compose files. Imports only the settings: it runs every 30 s.
"""

from __future__ import annotations

import urllib.request
from urllib.error import URLError
from urllib.parse import urlsplit

from config.ui import UiSettings, load_ui_settings


def health_request(ui: UiSettings) -> urllib.request.Request:
    """The loopback request to the health route, carrying the origin's host."""
    url = f"http://127.0.0.1:{ui.port}/api/health"
    return urllib.request.Request(url, headers={"Host": urlsplit(ui.origin).netloc})


def check(ui: UiSettings) -> int:
    """0 when the health route answers 200 within the timeout, else 1 (never raises)."""
    try:
        # A fixed http URL on loopback built above, never user input.
        with urllib.request.urlopen(  # noqa: S310  # nosec B310
            health_request(ui),
            timeout=ui.container_health_timeout_seconds,
        ) as response:
            return 0 if response.status == 200 else 1
    except (URLError, OSError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(check(load_ui_settings()))
