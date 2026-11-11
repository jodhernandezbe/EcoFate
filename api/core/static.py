"""The static frontend mount: it answers only reads, so an unknown API path is a plain 404."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

READ_METHODS = ("GET", "HEAD")


class FrontendFiles(StaticFiles):
    """``StaticFiles`` that answers 404 (not 405) to a write: a removed route such as
    ``POST /api/v1/settings/census-key`` falls through to this mount and must look unknown."""

    async def get_response(self, path: str, scope: Scope):  # noqa: ANN201 (starlette's own type)
        if scope["method"] not in READ_METHODS:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)
