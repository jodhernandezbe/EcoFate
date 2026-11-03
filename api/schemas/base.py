"""Base class of every contract model: immutable, and unknown fields are rejected."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Frozen Pydantic model that forbids extra fields (validate at the boundary once)."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_serialization_defaults_required=True,
    )
