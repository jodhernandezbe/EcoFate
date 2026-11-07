"""Wire model of the liveness endpoint (used by container health checks, not by the frontend)."""

from __future__ import annotations

from typing import Literal

from api.schemas.base import ContractModel


class HealthResponse(ContractModel):
    """The web program is serving requests."""

    status: Literal["ok"] = "ok"
