"""Sanitised error handling: a generic message and a correlation id, never the details.

Details go to the (redacted) server log under the same correlation id. Responses never echo
exception text, request headers, request bodies or submitted values.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.key_vault import InvalidKeyError, KeychainUnavailableError
from app.turns.failures import new_correlation_id

logger = logging.getLogger("api")
GENERIC_ERROR = "Something went wrong. Try again."
__all__ = [
    "GENERIC_ERROR",
    "FieldRejected",
    "Refusal",
    "error_body",
    "install_exception_handlers",
    "new_correlation_id",
]


class Refusal(Exception):  # noqa: N818  # not an error: an expected, answered refusal
    """A request the service refuses with a fixed, user-safe message (and maybe headers)."""

    def __init__(self, status: int, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.headers = headers


class FieldRejected(Exception):  # noqa: N818  # not an error: an expected, answered refusal
    """One field of the request body is not acceptable; the answer is a 422 naming it."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def error_body(message: str, correlation_id: str) -> dict[str, str]:
    """The only error shape the API returns."""
    return {"error": message, "correlation_id": correlation_id}


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = new_correlation_id()
    logger.error("unhandled error %s on %s", correlation_id, request.url.path, exc_info=exc)
    return JSONResponse(error_body(GENERIC_ERROR, correlation_id), status_code=500)


async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]  # no `input`
    body = {**error_body("Invalid request.", new_correlation_id()), "fields": fields}
    return JSONResponse(body, status_code=422)


async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        error_body(str(exc.detail), new_correlation_id()),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _refusal(request: Request, exc: Refusal) -> JSONResponse:
    body = error_body(exc.detail, new_correlation_id())
    return JSONResponse(body, status_code=exc.status, headers=exc.headers)


async def _field(request: Request, exc: FieldRejected) -> JSONResponse:
    fields = [{"loc": ["body", exc.field], "msg": exc.message}]
    body = {**error_body("Invalid request.", new_correlation_id()), "fields": fields}
    return JSONResponse(body, status_code=422)


async def _invalid_key(request: Request, exc: InvalidKeyError) -> JSONResponse:
    return JSONResponse(error_body(str(exc), new_correlation_id()), status_code=422)


async def _keychain(request: Request, exc: KeychainUnavailableError) -> JSONResponse:
    return JSONResponse(error_body(str(exc), new_correlation_id()), status_code=503)


def install_exception_handlers(app: FastAPI) -> None:
    """Register the sanitised handlers on ``app``."""
    app.add_exception_handler(Exception, _unhandled)
    app.add_exception_handler(RequestValidationError, _validation)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(StarletteHTTPException, _http)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(Refusal, _refusal)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(FieldRejected, _field)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(InvalidKeyError, _invalid_key)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(KeychainUnavailableError, _keychain)  # pyright: ignore[reportArgumentType]
