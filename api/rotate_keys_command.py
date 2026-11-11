"""``python -m api rotate-keys``: re-seal every stored user key under the current KEK.

Set the new key-encryption key as current and keep the old one in the previous-key variable
named in ``[byok]``, run this command, then remove the previous variable. Prints counts only.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

from api.services.database import open_database
from api.services.key_setup import build_key_services, load_key_config
from app.user_key_vault import RotationReport
from config.byok import get_byok_settings
from config.database import get_database_settings

SUMMARY = "Re-sealed {resealed}, already current {already_current}, unreadable {unreadable}."


async def _run() -> RotationReport:
    keks, operator = load_key_config(os.environ)
    async with open_database(os.environ, get_database_settings()) as database:
        services = build_key_services(keks, operator, database.credentials)
        return await services.vault.rotate(get_byok_settings().rotation_batch_size)


def summary(report: RotationReport) -> str:
    """The one-line counts the command prints (never a key, a user or a row)."""
    return SUMMARY.format(
        resealed=report.resealed,
        already_current=report.already_current,
        unreadable=report.unreadable,
    )


def main(argv: Sequence[str] = ()) -> None:
    """Run the rotation and print its counts; exits non-zero when rows are unreadable."""
    if argv:
        raise SystemExit("rotate-keys takes no arguments.")
    report = asyncio.run(_run())
    print(summary(report))
    if report.unreadable:
        raise SystemExit(1)
