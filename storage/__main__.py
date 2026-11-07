"""Migration commands: ``python -m storage upgrade | current | downgrade <revision>``.

Run explicitly (``make migrate``, or the one-shot compose service); the web program never
migrates by itself.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from alembic import command

from config.database import get_database_settings
from storage.engine import DatabaseSetupError, create_engine, database_url
from storage.revisions import alembic_config, current_revision, head_revision


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m storage", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upgrade", help="apply every migration up to the latest")
    commands.add_parser("current", help="print the revision; exit 1 unless it is the latest")
    down = commands.add_parser("downgrade", help="roll back to a revision (or 'base')")
    down.add_argument("revision")
    return parser


async def _read_current_revision() -> str | None:
    settings = get_database_settings()
    engine = create_engine(database_url(os.environ, settings), settings)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(current_revision)
    finally:
        await engine.dispose()


def _current() -> int:
    revision = asyncio.run(_read_current_revision())
    print(revision or "(none)")
    return 0 if revision == head_revision() else 1


def _run(arguments: argparse.Namespace) -> int:
    if arguments.command == "upgrade":
        command.upgrade(alembic_config(), "head")
    elif arguments.command == "downgrade":
        command.downgrade(alembic_config(), arguments.revision)
    else:
        return _current()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one migration command; returns the process exit code."""
    arguments = _build_parser().parse_args(argv)
    try:
        return _run(arguments)
    except DatabaseSetupError as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
