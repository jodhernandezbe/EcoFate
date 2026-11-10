"""``python -m api create-admin --email <address> [--password-stdin]``.

Creates a verified administrator, or promotes an existing account. The password is read from a
hidden prompt (asked twice), or from the first line of standard input with ``--password-stdin``
for scripted deploys; it is never an argument or an environment variable, and never printed.
Without ``--password-stdin`` the command refuses to run unless standard input is a terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from api.services.auth.admin import (
    AdminResult,
    AdminSetupError,
    create_or_promote_admin,
    exists,
)
from api.services.auth.email_address import InvalidEmailError
from api.services.auth.passwords import PasswordPolicyError, Passwords
from api.services.database import open_database
from config.auth import get_auth_settings
from config.database import get_database_settings

NOT_A_TERMINAL = (
    "create-admin asks for the password on a terminal. Run it in one, or pipe the password "
    "with --password-stdin."
)
MISMATCH = "The two passwords differ."
Prompt = Callable[[str], str]


def build_parser() -> argparse.ArgumentParser:
    """The command's arguments (the password is deliberately not one of them)."""
    parser = argparse.ArgumentParser(prog="python -m api create-admin", description=__doc__)
    parser.add_argument("--email", required=True, help="the administrator's email address")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from the first line of standard input",
    )
    return parser


def read_password(
    *,
    from_stdin: bool,
    stdin: TextIO,
    prompt: Prompt = getpass.getpass,
    optional: bool = False,
) -> str | None:
    """The password, from standard input or a hidden prompt; None when ``optional`` and empty.

    Raises:
        SystemExit: Standard input is not a terminal and ``--password-stdin`` was not given, or
            the two typed passwords differ.
    """
    if from_stdin:
        return stdin.readline().rstrip("\r\n") or None
    if not stdin.isatty():
        raise SystemExit(NOT_A_TERMINAL)
    label = " (Enter keeps the current one)" if optional else ""
    first = prompt(f"Password{label}: ")
    if not first and optional:
        return None
    if prompt("Repeat the password: ") != first:
        raise SystemExit(MISMATCH)
    return first


async def _run(arguments: argparse.Namespace, stdin: TextIO, prompt: Prompt) -> str:
    settings = get_database_settings()
    passwords = Passwords(get_auth_settings())
    async with open_database(os.environ, settings) as database:
        known = await exists(database.accounts.users, arguments.email)
        password = read_password(
            from_stdin=arguments.password_stdin,
            stdin=stdin,
            prompt=prompt,
            optional=known,
        )
        done = await create_or_promote_admin(
            database.accounts.users,
            passwords,
            arguments.email,
            password,
        )
    return _summary(done)


def _summary(done: AdminResult) -> str:
    verb = "Created" if done.created else "Promoted"
    kept = "" if done.password_changed else " (password unchanged)"
    return f"{verb} administrator {done.user.email}{kept}."


def main(argv: Sequence[str], stdin: TextIO = sys.stdin, prompt: Prompt = getpass.getpass) -> None:
    """Run the command; exits with a fixed message when it cannot."""
    arguments = build_parser().parse_args(list(argv))
    try:
        message = asyncio.run(_run(arguments, stdin, prompt))
    except (InvalidEmailError, PasswordPolicyError, AdminSetupError) as error:
        raise SystemExit(str(error)) from None
    print(message)
