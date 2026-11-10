"""The account flows: sign up, verify, sign in and out, recover, and manage an account.

Every flow answers from fixed messages. Whether an email has an account is never visible in a
status, a body or (beyond what one database read costs) the time a request takes: sign-up,
resend and recovery answer the same either way, and a sign-in for an unknown email still pays
for one password verification. Emails are returned to the caller to send after the response.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from api.core.exceptions import FieldRejected, Refusal
from api.services.auth.email_address import InvalidEmailError, normalise_email
from api.services.auth.mailer import Mail
from api.services.auth.messages import existing_account_mail, reset_mail, verification_mail
from api.services.auth.passwords import PasswordPolicyError, Passwords
from api.services.auth.sessions import SessionService
from api.services.auth.stores import Accounts
from api.services.auth.throttle import Throttle, attempt_keys, email_key
from api.services.auth.tokens import TokenService
from api.services.threads import ThreadStore
from config.auth import AuthSettings
from storage.account_model import TokenPurpose, User

SIGNUP_CLOSED = "Sign-up is closed on this server."
INVALID_CREDENTIALS = "Incorrect email or password."
INVALID_LINK = "This link is invalid or has expired."
WRONG_PASSWORD = "The password is incorrect."  # noqa: S105  # nosec B105  # a message, not a secret  # pragma: allowlist secret
TOO_MANY = "Too many attempts. Try again later."
LOGIN = "login"
RECOVER = "recover"


@dataclass(frozen=True)
class SignedIn:
    """A successful sign-in: the account and the new session's token (for the cookie)."""

    user: User
    session_token: str


@dataclass(frozen=True)
class VerificationRequired:
    """The password was right but the email is not verified yet: no session was made."""


SignInResult = SignedIn | VerificationRequired


@dataclass(frozen=True)
class AuthParts:
    """What the flows are built from.

    Attributes:
        accounts: The stores.
        passwords: Policy and hashing.
        tokens: Emailed single-use tokens.
        sessions: Session cookies.
        throttle: Failed-attempt limits.
        threads: The conversation store (an account's threads go with it).
        settings: Whether sign-up is open.
        base_url: The web app's origin, for the links in emails.
    """

    accounts: Accounts
    passwords: Passwords
    tokens: TokenService
    sessions: SessionService
    throttle: Throttle
    threads: ThreadStore
    settings: AuthSettings
    base_url: str


def _valid_email(raw: str) -> str:
    try:
        return normalise_email(raw)
    except InvalidEmailError as error:
        raise FieldRejected("email", str(error)) from None


def _password_ok_for(
    passwords: Passwords,
    password: str,
    email: str,
    field: str = "password",
) -> None:
    try:
        passwords.check_policy(password, email)
    except PasswordPolicyError as error:
        raise FieldRejected(field, str(error)) from None


def _length_ok(passwords: Passwords, password: str) -> None:
    try:
        passwords.check_length(password)
    except PasswordPolicyError as error:
        raise FieldRejected("password", str(error)) from None


def _maybe_email(raw: str) -> str | None:
    """The normalised address, or None when the text is not one (never an error)."""
    try:
        return normalise_email(raw)
    except InvalidEmailError:
        return None


class AuthService:
    """Runs the account flows over the stores.

    Args:
        parts: The collaborators.
    """

    def __init__(self, parts: AuthParts) -> None:
        self._p = parts

    async def _guard(self, keys: list[str]) -> None:
        """Refuse with 429 and ``Retry-After`` when any key reached the limit."""
        wait = await self._p.throttle.retry_after(keys)
        if wait is not None:
            raise Refusal(429, TOO_MANY, {"Retry-After": str(wait)})

    # --- sign up and verification ---------------------------------------------------------

    async def sign_up(self, email_raw: str, password: str) -> Mail:
        """Create an unverified account and return its verification mail; when the email already
        has an account, none is made and the mail goes to its owner instead (the caller sees the
        same either way).

        Raises:
            Refusal: Sign-up is closed (403).
            FieldRejected: The email or password is not acceptable (422).
        """
        if not self._p.settings.signup_open:
            raise Refusal(403, SIGNUP_CLOSED)
        email = _valid_email(email_raw)
        _password_ok_for(self._p.passwords, password, email)
        hashed = await self._p.passwords.hash(password)  # the same work for a taken email
        user = await self._p.accounts.users.create(email, hashed)
        if user is None:
            return existing_account_mail(email, self._p.base_url)
        token = await self._p.tokens.issue(user.id, TokenPurpose.VERIFY_EMAIL)
        return verification_mail(email, self._p.base_url, token)

    async def verify_email(self, token: str) -> None:
        """Mark the address verified with a valid single-use token.

        Raises:
            Refusal: The token is unknown, expired or already used (400).
        """
        user_id = await self._p.tokens.consume(TokenPurpose.VERIFY_EMAIL, token)
        if user_id is None or not await self._p.accounts.users.mark_verified(user_id):
            raise Refusal(400, INVALID_LINK)

    async def resend_verification(self, email_raw: str, address: str) -> Mail | None:
        """A new verification mail for an unverified account; None for any other address.

        Raises:
            Refusal: Too many recovery requests from this address or for this email (429).
        """
        user = await self._recovery_target(email_raw, address)
        if user is None or user.verified:
            return None
        token = await self._p.tokens.issue(user.id, TokenPurpose.VERIFY_EMAIL)
        return verification_mail(user.email, self._p.base_url, token)

    # --- sign in and out ------------------------------------------------------------------

    async def sign_in(
        self,
        email_raw: str,
        password: str,
        presented: str | None,
        address: str,
    ) -> SignInResult:
        """Check the credentials and start a new session (ending any the browser presented).

        Raises:
            Refusal: Too many failures (429, the password is not even checked), or the email
                and password do not match (401, the same for an unknown email).
        """
        email = _maybe_email(email_raw)
        keys = attempt_keys(LOGIN, email_raw if email is None else email, address)
        await self._guard(keys)
        user = None if email is None else await self._p.accounts.users.by_email(email)
        if not await self._matches(user, password):
            await self._p.throttle.fail(keys)
            raise Refusal(401, INVALID_CREDENTIALS)
        if user is None or not user.verified:
            return VerificationRequired()
        await self._p.throttle.forgive([email_key(LOGIN, user.email)])
        await self._upgrade_hash(user, password)
        return SignedIn(user, await self._p.sessions.start(user.id, presented))

    async def _matches(self, user: User | None, password: str) -> bool:
        if user is None:
            await self._p.passwords.verify_unknown(password)
            return False
        return await self._p.passwords.verify(user.password_hash, password)

    async def _upgrade_hash(self, user: User, password: str) -> None:
        if self._p.passwords.needs_rehash(user.password_hash):
            fresh = await self._p.passwords.hash(password)
            await self._p.accounts.users.set_password(user.id, fresh)

    async def sign_out(self, session_token: str | None) -> None:
        """End the session the cookie names."""
        await self._p.sessions.end(session_token)

    # --- recovery -------------------------------------------------------------------------

    async def _recovery_target(self, email_raw: str, address: str) -> User | None:
        """Count a recovery request, and find the account it names (None when there is none)."""
        email = _maybe_email(email_raw)
        keys = attempt_keys(RECOVER, email_raw if email is None else email, address)
        await self._guard(keys)
        await self._p.throttle.fail(keys)
        return None if email is None else await self._p.accounts.users.by_email(email)

    async def forgot_password(self, email_raw: str, address: str) -> Mail | None:
        """A reset mail for the account with this email; None when there is none.

        Raises:
            Refusal: Too many recovery requests from this address or for this email (429).
        """
        user = await self._recovery_target(email_raw, address)
        if user is None:
            return None
        token = await self._p.tokens.issue(user.id, TokenPurpose.RESET_PASSWORD)
        return reset_mail(user.email, self._p.base_url, token)

    async def reset_password(self, token: str, new_password: str) -> None:
        """Set a new password with a valid single-use token; every session of the account ends.

        Raises:
            FieldRejected: The password is not acceptable (422; the token stays usable).
            Refusal: The token is unknown, expired or already used (400).
        """
        _length_ok(self._p.passwords, new_password)
        user_id = await self._p.tokens.consume(TokenPurpose.RESET_PASSWORD, token)
        user = None if user_id is None else await self._p.accounts.users.by_id(user_id)
        if user is None:
            raise Refusal(400, INVALID_LINK)
        _password_ok_for(self._p.passwords, new_password, user.email)
        await self._replace_password(user.id, new_password)
        await self._p.tokens.invalidate(user.id, TokenPurpose.RESET_PASSWORD)
        await self._p.sessions.end_all(user.id)

    async def _replace_password(self, user_id: UUID, password: str) -> None:
        await self._p.accounts.users.set_password(user_id, await self._p.passwords.hash(password))

    # --- the signed-in account ------------------------------------------------------------

    async def _confirm(self, user: User, password: str, address: str) -> None:
        """Require the account's current password (throttled like a sign-in)."""
        keys = attempt_keys(LOGIN, user.email, address)
        await self._guard(keys)
        if not await self._p.passwords.verify(user.password_hash, password):
            await self._p.throttle.fail(keys)
            raise Refusal(403, WRONG_PASSWORD)

    async def change_password(
        self,
        user: User,
        current: str,
        new: str,
        keep_session: str | None,
        address: str,
    ) -> None:
        """Set a new password and end every other session of the account.

        Raises:
            FieldRejected: The new password is not acceptable (422).
            Refusal: The current password is wrong (403) or there were too many failures (429).
        """
        _password_ok_for(self._p.passwords, new, user.email, "new_password")
        await self._confirm(user, current, address)
        await self._replace_password(user.id, new)
        await self._p.sessions.end_all(user.id, keep_session)

    async def sign_out_everywhere(self, user: User) -> None:
        """End every session of the account, this one included."""
        await self._p.sessions.end_all(user.id)

    async def delete_account(self, user: User, password: str, address: str) -> None:
        """Delete the account with its sessions, tokens, threads and checkpoints.

        Raises:
            Refusal: The password is wrong (403) or there were too many failures (429).
        """
        await self._confirm(user, password, address)
        await self._p.threads.forget_owner(user.id)
        await self._p.accounts.users.delete(user.id)
