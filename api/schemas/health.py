"""Wire model of the health endpoint (used by container health checks, not by the frontend)."""

from __future__ import annotations

from typing import Literal

from api.schemas.base import ContractModel


class HealthResponse(ContractModel):
    """``ok`` while the program serves and its database answers; ``unavailable`` otherwise."""

    status: Literal["ok", "unavailable"] = "ok"
