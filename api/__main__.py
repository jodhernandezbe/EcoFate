"""Command line: ``uv run python -m api`` serves the web interface on loopback.

``create-admin --email <address>`` creates (or promotes) the first administrator; see
``api/admin_command.py``.

``rotate-keys`` re-seals every stored user key under the current key-encryption key; see
``api/rotate_keys_command.py``.

``--container`` binds the address in ``[ui.container]`` instead (inside a container, where the
port is published on the host's loopback only), and a loopback SMTP host is taken to be Mailpit;
the origin checks still use ``[ui]``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from uvicorn.config import LOGGING_CONFIG

from api.admin_command import main as create_admin
from api.core.config import ui_settings
from api.core.logging_filter import uvicorn_log_config
from api.main import create_app
from api.rotate_keys_command import main as rotate_keys
from api.services.key_setup import process_secret_values
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


def _run_command(argv: Sequence[str]) -> bool:
    """Run ``create-admin`` or ``rotate-keys`` when ``argv`` starts with it; whether it did."""
    commands = {"create-admin": create_admin, "rotate-keys": rotate_keys}
    command = commands.get(argv[0]) if argv else None
    if command is None:
        return False
    load_dotenv()
    command(argv[1:])
    return True


def main(argv: Sequence[str] = ()) -> None:
    """Serve the API and the built frontend on the configured loopback address.

    Loads ``.env`` first, like the command line program, so the tools find the operator's
    service keys (Census, CompTox). Users' OpenAI keys are never read from there: each comes
    from the user's encrypted row.

    Args:
        argv: Command line arguments after the program name (``--container``).
    """
    if _run_command(argv):
        return
    container = _arguments(argv).container
    load_dotenv()
    # after .env, which holds the token; every secret read from it is hidden in the spans
    configure_telemetry(get_telemetry_settings(), process_secret_values(os.environ))
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
