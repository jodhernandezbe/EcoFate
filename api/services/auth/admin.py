"""The first administrator: create a verified admin account, or promote an existing one.

There is no default admin and no default password. The caller (the ``create-admin`` command)
supplies the password it read from a hidden prompt or standard input; this module never reads
the environment or the command line.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.services.auth.email_address import normalise_email
from api.services.auth.passwords import Passwords
from api.services.auth.stores import UserStore
from storage.account_model import Role, User


class AdminSetupError(Exception):
    """The administrator cannot be set up; ``str(error)`` is safe to show."""


@dataclass(frozen=True)
class AdminResult:
    """What the command did.

    Attributes:
        user: The administrator.
        created: True for a new account, False for a promoted one.
        password_changed: Whether the password was set (always for a new account).
    """

    user: User
    created: bool
    password_changed: bool


async def exists(users: UserStore, email_raw: str) -> bool:
    """Whether an account with this email exists (the command asks for a password differently)."""
    return await users.by_email(normalise_email(email_raw)) is not None


async def create_or_promote_admin(
    users: UserStore,
    passwords: Passwords,
    email_raw: str,
    password: str | None,
) -> AdminResult:
    """Make the account with this email a verified administrator.

    A new account needs a password (checked against the policy). For an existing account the
    password is kept unless a new one is given.

    Raises:
        InvalidEmailError: The address is not valid.
        PasswordPolicyError: The password breaks the policy.
        AdminSetupError: A new account was asked for without a password.
    """
    email = normalise_email(email_raw)
    existing = await users.by_email(email)
    if password:
        passwords.check_policy(password, email)
    if existing is None:
        return await _create(users, passwords, email, password)
    if password:
        await users.set_password(existing.id, await passwords.hash(password))
    await users.set_role(existing.id, Role.ADMIN)
    await users.mark_verified(existing.id)
    promoted = await users.by_id(existing.id)
    if promoted is None:
        raise AdminSetupError("The account disappeared while it was being promoted.")
    return AdminResult(promoted, created=False, password_changed=bool(password))


async def _create(
    users: UserStore,
    passwords: Passwords,
    email: str,
    password: str | None,
) -> AdminResult:
    if not password:
        raise AdminSetupError("A new administrator needs a password.")
    hashed = await passwords.hash(password)
    user = await users.create(email, hashed, role=Role.ADMIN, verified=True)
    if user is None:
        raise AdminSetupError("An account with this email appeared while it was being created.")
    return AdminResult(user, created=True, password_changed=True)
