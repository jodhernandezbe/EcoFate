"""``Depends()`` providers that decide who is calling: ``current_user`` and ``require_admin``.

A request without a valid session is answered 401 with a generic message before any handler
runs. A signed-in user without the ``admin`` role is answered 404 by ``require_admin``, with the
body of an unknown route, so the admin endpoints do not advertise themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, HTTPException, Request

from api.core.exceptions import Refusal
from storage.account_model import Role, User

if TYPE_CHECKING:
    from api.services.auth.runtime import AuthRuntime

UNAUTHENTICATED = "Sign in to continue."
ADMIN_ONLY = "Only an administrator can change this server's API keys."


def auth_runtime(request: Request) -> AuthRuntime:
    """The account services of this app."""
    return cast("AuthRuntime", request.app.state.auth)


async def current_user(request: Request) -> User:
    """The account behind the request's session cookie.

    Raises:
        Refusal: 401 when there is no cookie, or it names no live session.
    """
    runtime = auth_runtime(request)
    token = request.cookies.get(runtime.settings.cookie_name)
    user = await runtime.sessions.resolve(token)
    if user is None:
        raise Refusal(401, UNAUTHENTICATED)
    return user


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """The signed-in administrator; anyone else gets the 404 of an unknown route."""
    if user.role is not Role.ADMIN:
        raise HTTPException(status_code=404)
    return user


async def require_admin_action(user: Annotated[User, Depends(current_user)]) -> User:
    """The signed-in administrator, for an action on server-wide state whose route is not
    hidden (the key routes: everyone may see whether a key is set); anyone else gets 403."""
    if user.role is not Role.ADMIN:
        raise Refusal(403, ADMIN_ONLY)
    return user


CurrentUser = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_admin)]
