"""Wire models of the account routes.

Passwords are ``SecretStr`` so they never appear in a repr or a log line; their length is
checked by the password policy (a 422 naming the field), with a generous cap here so an absurd
body is refused before any hashing.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, SecretStr

from api.schemas.base import ContractModel

Email = Annotated[str, Field(max_length=320)]
Password = Annotated[SecretStr, Field(max_length=1024)]
Token = Annotated[str, Field(max_length=256)]


class SignUpRequest(ContractModel):
    """``POST /api/v1/auth/signup``."""

    email: Email
    password: Password


class SignInRequest(ContractModel):
    """``POST /api/v1/auth/signin``."""

    email: Email
    password: Password


class EmailRequest(ContractModel):
    """``POST /api/v1/auth/resend`` and ``/forgot``: the address to mail."""

    email: Email


class TokenRequest(ContractModel):
    """``POST /api/v1/auth/verify``: the token from the emailed link (sent in the body)."""

    token: Token


class ResetRequest(ContractModel):
    """``POST /api/v1/auth/reset``: the token from the emailed link and the new password."""

    token: Token
    password: Password


class ChangePasswordRequest(ContractModel):
    """``POST /api/v1/account/password``."""

    current_password: Password
    new_password: Password


class DeleteAccountRequest(ContractModel):
    """``POST /api/v1/account/delete``: the account's password confirms it."""

    password: Password


class AcceptedResponse(ContractModel):
    """The same answer whether or not the email has an account."""

    status: Literal["accepted"] = "accepted"


class UserInfo(ContractModel):
    """The signed-in user: never a password hash or a token."""

    id: str
    email: str
    role: Literal["user", "admin"]
    verified: bool


class SignInResponse(ContractModel):
    """``signed_in`` (with the user; the session is the cookie) or ``verification_required``
    (the password was right but the email is not verified; no session was made)."""

    state: Literal["signed_in", "verification_required"]
    user: UserInfo | None
