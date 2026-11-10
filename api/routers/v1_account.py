"""Account management for the signed-in user: password, sign out everywhere, delete. Thin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from api.core.session_guard import CurrentUser, auth_runtime
from api.dependencies import get_client_address
from api.routers.v1_auth import clear_session_cookie
from api.schemas.auth import ChangePasswordRequest, DeleteAccountRequest
from api.services.auth.runtime import AuthRuntime

router = APIRouter(prefix="/api/v1/account", tags=["account"])
Runtime = Annotated[AuthRuntime, Depends(auth_runtime)]
Address = Annotated[str, Depends(get_client_address)]
_NO_CONTENT = 204


@router.post("/password", status_code=_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUser,
    runtime: Runtime,
    address: Address,
) -> Response:
    """Change the password (the current one is required); every other session ends."""
    keep = request.cookies.get(runtime.settings.cookie_name)
    current = body.current_password.get_secret_value()
    new = body.new_password.get_secret_value()
    await runtime.service.change_password(user, current, new, keep, address)
    return Response(status_code=_NO_CONTENT)


@router.post("/sign-out-everywhere", status_code=_NO_CONTENT)
async def sign_out_everywhere(user: CurrentUser, runtime: Runtime) -> Response:
    """End every session of the account, this one included."""
    await runtime.service.sign_out_everywhere(user)
    response = Response(status_code=_NO_CONTENT)
    clear_session_cookie(response, runtime)
    return response


@router.post("/delete", status_code=_NO_CONTENT)
async def delete_account(
    body: DeleteAccountRequest,
    user: CurrentUser,
    runtime: Runtime,
    address: Address,
) -> Response:
    """Delete the account with its threads, sessions and tokens (the password confirms it)."""
    await runtime.service.delete_account(user, body.password.get_secret_value(), address)
    response = Response(status_code=_NO_CONTENT)
    clear_session_cookie(response, runtime)
    return response
