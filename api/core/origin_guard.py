"""Reject cross-site and DNS-rebinding requests before any route runs."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from api.core.exceptions import error_body, new_correlation_id

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


class OriginGuard:
    """ASGI middleware: ``Host`` must be the configured host and port for every request, and
    state-changing requests must carry the API's own ``Origin`` (or ``Referer``)."""

    def __init__(self, app: ASGIApp, *, origin: str) -> None:
        self.app = app
        self.origin = origin
        self.host = urlsplit(origin).netloc

    def _allowed(self, request: Request) -> bool:
        if request.headers.get("host", "") != self.host:
            return False
        if request.method in SAFE_METHODS:
            return True
        sent = request.headers.get("origin") or _origin_of(request.headers.get("referer", ""))
        return sent == self.origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self._allowed(Request(scope)):
            await self.app(scope, receive, send)
            return
        denied: Response = JSONResponse(
            error_body("Request not allowed.", new_correlation_id()),
            status_code=403,
        )
        await denied(scope, receive, send)
