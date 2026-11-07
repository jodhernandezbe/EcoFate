"""Command line: ``uv run python -m api`` serves the web interface on loopback.

``--container`` binds the address in ``[ui.container]`` instead (inside a container, where the
port is published on the host's loopback only) and reads the keys from the environment, since a
container has no OS keychain; the origin checks still use ``[ui]``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from uvicorn.config import LOGGING_CONFIG

from api.core.config import ui_settings
from api.core.logging_filter import uvicorn_log_config
from api.main import create_app
from app.telemetry import configure_telemetry
from config.telemetry import get_telemetry_settings

BUILD_HINT = (
    "The frontend is not built. Run: npm --prefix frontend ci && npm --prefix frontend run build"
)


def require_built_frontend(dist: Path) -> None:
    """Exit with the build command when ``dist`` has no built frontend."""
    if not (dist / "index.html").is_file():
        raise SystemExit(BUILD_HINT)


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m api", description=__doc__)
    parser.add_argument(
        "--container",
        action="store_true",
        help="bind the [ui.container] address (inside a container) instead of [ui].host",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] = ()) -> None:
    """Serve the API and the built frontend on the configured loopback address.

    Loads ``.env`` first, like the command line program, so the tools find their service
    keys (Census, CompTox). The OpenAI key is not read from there: it comes from the keychain.

    Args:
        argv: Command line arguments after the program name (``--container``).
    """
    container = _arguments(argv).container
    load_dotenv()
    configure_telemetry(get_telemetry_settings())  # after .env, which may hold the token
    settings = ui_settings()
    require_built_frontend(settings.frontend_dist)
    uvicorn.run(
        create_app(settings, keys_from_environment=container),
        host=settings.container_bind_host if container else settings.host,
        port=settings.port,
        log_config=uvicorn_log_config(LOGGING_CONFIG),
    )


if __name__ == "__main__":
    main(sys.argv[1:])
