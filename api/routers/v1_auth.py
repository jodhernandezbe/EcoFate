"""Authentication routes: sign up, verify, sign in and out, recover a password. Thin handlers.

Sign-up, resend and forgot answer 202 with the same body whether or not the address has an
account; their emails are sent after the response.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from api.core.session_guard import CurrentUser, auth_runtime
from api.dependencies import get_client_address
from api.schemas.auth import (
    AcceptedResponse,
    EmailRequest,
    ResetRequest,
    SignInRequest,
    SignInResponse,
    SignUpRequest,
    TokenRequest,
    UserInfo,
)
from api.services.auth.flows import VerificationRequired
from api.services.auth.mailer import deliver
from api.services.auth.runtime import AuthRuntime
from storage.account_model import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
Runtime = Annotated[AuthRuntime, Depends(auth_runtime)]
Address = Annotated[str, Depends(get_client_address)]
_ACCEPTED = 202
_NO_CONTENT = 204


def user_info(user: User) -> UserInfo:
    """The user as the interface sees them."""
    return UserInfo(id=str(user.id), email=user.email, role=user.role.value, verified=user.verified)


def clear_session_cookie(response: Response, runtime: AuthRuntime) -> None:
    """Ask the browser to forget the session cookie."""
    response.delete_cookie(runtime.sessions.cookie_name, path="/", httponly=True)


@router.post("/signup", status_code=_ACCEPTED)
async def sign_up(
    body: SignUpRequest,
    background: BackgroundTasks,
    runtime: Runtime,
) -> AcceptedResponse:
    """Create an account (or tell its owner someone tried) and mail the verification link."""
    mail = await runtime.service.sign_up(body.email, body.password.get_secret_value())
    background.add_task(deliver, runtime.mailer, mail)
    return AcceptedResponse()


@router.post("/verify", status_code=_NO_CONTENT)
async def verify_email(body: TokenRequest, runtime: Runtime) -> Response:
    """Verify the address with the token from the emailed link."""
    await runtime.service.verify_email(body.token)
    return Response(status_code=_NO_CONTENT)


@router.post("/resend", status_code=_ACCEPTED)
async def resend_verification(
    body: EmailRequest,
    background: BackgroundTasks,
    runtime: Runtime,
    address: Address,
) -> AcceptedResponse:
    """Mail a new verification link to an unverified account (the answer never says whether)."""
    mail = await runtime.service.resend_verification(body.email, address)
    if mail is not None:
        background.add_task(deliver, runtime.mailer, mail)
    return AcceptedResponse()


@router.post("/signin")
async def sign_in(
    body: SignInRequest,
    request: Request,
    response: Response,
    runtime: Runtime,
    address: Address,
) -> SignInResponse:
    """Start a session (the cookie replaces any the browser sent), or say verification is due."""
    presented = request.cookies.get(runtime.settings.cookie_name)
    password = body.password.get_secret_value()
    result = await runtime.service.sign_in(body.email, password, presented, address)
    if isinstance(result, VerificationRequired):
        return SignInResponse(state="verification_required", user=None)
    response.set_cookie(value=result.session_token, **runtime.sessions.cookie())
    return SignInResponse(state="signed_in", user=user_info(result.user))


@router.post("/signout", status_code=_NO_CONTENT)
async def sign_out(request: Request, runtime: Runtime, _user: CurrentUser) -> Response:
    """End this session on the server and clear the cookie."""
    await runtime.service.sign_out(request.cookies.get(runtime.settings.cookie_name))
    response = Response(status_code=_NO_CONTENT)
    clear_session_cookie(response, runtime)
    return response


@router.post("/forgot", status_code=_ACCEPTED)
async def forgot_password(
    body: EmailRequest,
    background: BackgroundTasks,
    runtime: Runtime,
    address: Address,
) -> AcceptedResponse:
    """Mail a reset link to the account with this email (the answer never says whether)."""
    mail = await runtime.service.forgot_password(body.email, address)
    if mail is not None:
        background.add_task(deliver, runtime.mailer, mail)
    return AcceptedResponse()


@router.post("/reset", status_code=_NO_CONTENT)
async def reset_password(body: ResetRequest, runtime: Runtime) -> Response:
    """Set a new password with the token from the emailed link; every session ends."""
    await runtime.service.reset_password(body.token, body.password.get_secret_value())
    response = Response(status_code=_NO_CONTENT)
    clear_session_cookie(response, runtime)
    return response


@router.get("/me")
async def me(user: CurrentUser) -> UserInfo:
    """The signed-in user (401 when there is none)."""
    return user_info(user)
