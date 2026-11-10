"""``python -m api create-admin``: the password is prompted or piped, never an argument."""

from __future__ import annotations

import asyncio
import contextlib
import io
from collections.abc import AsyncGenerator, Callable
from types import SimpleNamespace
from typing import Any, TextIO

import pytest

from api import admin_command
from api.services.auth.admin import AdminSetupError, create_or_promote_admin
from api.services.auth.email_address import InvalidEmailError
from api.services.auth.passwords import PasswordPolicyError, Passwords
from storage.account_model import Role
from tests.api.auth_support import fast_settings
from tests.fakes_accounts import FakeClock, in_memory_accounts

EMAIL = "root@example.com"
PASSWORD = "the first admin password"  # pragma: allowlist secret


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _prompts(*answers: str) -> Callable[[str], str]:
    queue = list(answers)
    return lambda _label: queue.pop(0)


def _passwords() -> Passwords:
    return Passwords(fast_settings())


# --- reading the password -------------------------------------------------------------------


def test_the_parser_has_no_password_argument() -> None:
    with pytest.raises(SystemExit):
        admin_command.build_parser().parse_args(["--email", EMAIL, "--password", "secret"])
    assert "password" not in vars(admin_command.build_parser().parse_args(["--email", EMAIL]))


def test_without_a_terminal_and_without_the_flag_the_command_refuses() -> None:
    with pytest.raises(SystemExit, match="terminal"):
        admin_command.read_password(from_stdin=False, stdin=io.StringIO("x\n"))


def test_with_the_flag_the_first_line_of_stdin_is_the_password() -> None:
    stdin: TextIO = io.StringIO(f"{PASSWORD}\nignored\n")
    assert admin_command.read_password(from_stdin=True, stdin=stdin) == PASSWORD
    assert admin_command.read_password(from_stdin=True, stdin=io.StringIO("")) is None


def test_on_a_terminal_the_password_is_asked_twice_and_must_match() -> None:
    ok = admin_command.read_password(
        from_stdin=False,
        stdin=_Terminal(),
        prompt=_prompts(PASSWORD, PASSWORD),
    )
    assert ok == PASSWORD
    with pytest.raises(SystemExit, match="differ"):
        admin_command.read_password(
            from_stdin=False,
            stdin=_Terminal(),
            prompt=_prompts(PASSWORD, "another"),
        )


def test_an_existing_account_may_keep_its_password_by_entering_nothing() -> None:
    kept = admin_command.read_password(
        from_stdin=False,
        stdin=_Terminal(),
        prompt=_prompts(""),
        optional=True,
    )
    assert kept is None


# --- creating and promoting -----------------------------------------------------------------


def test_a_new_admin_is_verified_has_the_admin_role_and_a_hashed_password() -> None:
    users = in_memory_accounts(FakeClock()).users
    done = asyncio.run(create_or_promote_admin(users, _passwords(), EMAIL, PASSWORD))
    assert done.created and done.password_changed
    assert (done.user.role, done.user.verified) == (Role.ADMIN, True)
    assert (
        done.user.password_hash.startswith("$argon2id$") and PASSWORD not in done.user.password_hash
    )


def test_a_new_admin_needs_a_password_that_meets_the_policy() -> None:
    users = in_memory_accounts(FakeClock()).users
    with pytest.raises(AdminSetupError):
        asyncio.run(create_or_promote_admin(users, _passwords(), EMAIL, None))
    with pytest.raises(PasswordPolicyError):
        asyncio.run(create_or_promote_admin(users, _passwords(), EMAIL, "short"))
    with pytest.raises(InvalidEmailError):
        asyncio.run(create_or_promote_admin(users, _passwords(), "nope", PASSWORD))
    assert asyncio.run(users.by_email(EMAIL)) is None


def test_promoting_an_existing_user_keeps_the_password_unless_a_new_one_is_given() -> None:
    users = in_memory_accounts(FakeClock()).users
    made = asyncio.run(users.create(EMAIL, "old-hash"))
    assert made is not None
    kept = asyncio.run(create_or_promote_admin(users, _passwords(), EMAIL, None))
    assert not kept.created and not kept.password_changed
    assert (kept.user.role, kept.user.verified, kept.user.password_hash) == (
        Role.ADMIN,
        True,
        "old-hash",
    )
    changed = asyncio.run(create_or_promote_admin(users, _passwords(), EMAIL, PASSWORD))
    assert (
        changed.password_changed
        and changed.user.password_hash != "old-hash"  # pragma: allowlist secret
    )  # pragma: allowlist secret


# --- the command, with the database replaced ------------------------------------------------


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Any:
    accounts = in_memory_accounts(FakeClock())

    @contextlib.asynccontextmanager
    async def fake_open(*_args: object) -> AsyncGenerator[Any]:
        yield SimpleNamespace(accounts=accounts)

    monkeypatch.setattr(admin_command, "open_database", fake_open)
    monkeypatch.setattr(admin_command, "get_auth_settings", fast_settings)
    return accounts


def test_the_command_creates_the_admin_and_never_prints_the_password(
    database: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin_command.main(
        ["--email", EMAIL],
        stdin=_Terminal(),
        prompt=_prompts(PASSWORD, PASSWORD),
    )
    out = capsys.readouterr()
    assert PASSWORD not in out.out + out.err and EMAIL in out.out
    admin = asyncio.run(database.users.by_email(EMAIL))
    assert admin is not None and admin.role is Role.ADMIN


def test_the_command_with_the_flag_reads_stdin(database: Any) -> None:
    admin_command.main(["--email", EMAIL, "--password-stdin"], stdin=io.StringIO(PASSWORD + "\n"))
    assert asyncio.run(database.users.by_email(EMAIL)) is not None


def test_the_command_refuses_without_a_terminal(database: Any) -> None:
    with pytest.raises(SystemExit, match="terminal"):
        admin_command.main(["--email", EMAIL], stdin=io.StringIO(""))
    assert asyncio.run(database.users.by_email(EMAIL)) is None


def test_the_command_promotes_and_keeps_the_password_on_an_empty_answer(
    database: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(database.users.create(EMAIL, "old-hash"))
    admin_command.main(["--email", EMAIL], stdin=_Terminal(), prompt=_prompts(""))
    promoted = asyncio.run(database.users.by_email(EMAIL))
    assert promoted is not None and promoted.role is Role.ADMIN
    assert (
        promoted.password_hash == "old-hash"  # pragma: allowlist secret
        and "unchanged" in capsys.readouterr().out  # pragma: allowlist secret
    )  # pragma: allowlist secret


def test_a_policy_failure_exits_with_its_message_and_no_traceback(database: Any) -> None:
    with pytest.raises(SystemExit, match="at least"):
        admin_command.main(["--email", EMAIL, "--password-stdin"], stdin=io.StringIO("short\n"))


def test_create_admin_is_reachable_from_the_package_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api import __main__ as entry

    seen: list[list[str]] = []
    monkeypatch.setattr(entry, "create_admin", seen.append)
    monkeypatch.setattr(entry, "load_dotenv", lambda: None)
    entry.main(["create-admin", "--email", EMAIL])
    assert seen == [["--email", EMAIL]]
