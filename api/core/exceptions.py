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
__all__ = ["GENERIC_ERROR", "error_body", "install_exception_handlers", "new_correlation_id"]


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
    )


async def _invalid_key(request: Request, exc: InvalidKeyError) -> JSONResponse:
    return JSONResponse(error_body(str(exc), new_correlation_id()), status_code=422)


async def _keychain(request: Request, exc: KeychainUnavailableError) -> JSONResponse:
    return JSONResponse(error_body(str(exc), new_correlation_id()), status_code=503)


def install_exception_handlers(app: FastAPI) -> None:
    """Register the sanitised handlers on ``app``."""
    app.add_exception_handler(Exception, _unhandled)
    app.add_exception_handler(RequestValidationError, _validation)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(StarletteHTTPException, _http)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(InvalidKeyError, _invalid_key)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(KeychainUnavailableError, _keychain)  # pyright: ignore[reportArgumentType]
