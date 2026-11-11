"""The whole contract as one JSON Schema document, from which the frontend types are generated."""

from __future__ import annotations

import json
from typing import Any, cast

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, models_json_schema

from api.schemas.auth import (
    AcceptedResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    EmailRequest,
    ResetRequest,
    SignInRequest,
    SignInResponse,
    SignUpRequest,
    TokenRequest,
    UserInfo,
)
from api.schemas.chat import ChatRequest, StreamEventSchema, ThreadSnapshot, UsageTotals
from api.schemas.monitoring import SessionDetailResponse, SessionsResponse
from api.schemas.quota import QuotaExhausted, QuotaStatus
from api.schemas.settings import (
    ClientConfig,
    KeysStatusResponse,
    KeyStatusResponse,
    KeyUpdatePayload,
)
from api.schemas.workspace import WorkspaceState

_MODELS: tuple[tuple[type[BaseModel], JsonSchemaMode], ...] = (
    (ChatRequest, "validation"),
    (KeyUpdatePayload, "validation"),
    (StreamEventSchema, "serialization"),
    (UsageTotals, "serialization"),
    (ThreadSnapshot, "serialization"),
    (KeyStatusResponse, "serialization"),
    (KeysStatusResponse, "serialization"),
    (ClientConfig, "serialization"),
    (WorkspaceState, "serialization"),
    (SessionsResponse, "serialization"),
    (SessionDetailResponse, "serialization"),
    (SignUpRequest, "validation"),
    (SignInRequest, "validation"),
    (EmailRequest, "validation"),
    (TokenRequest, "validation"),
    (ResetRequest, "validation"),
    (ChangePasswordRequest, "validation"),
    (DeleteAccountRequest, "validation"),
    (AcceptedResponse, "serialization"),
    (UserInfo, "serialization"),
    (SignInResponse, "serialization"),
    (QuotaStatus, "serialization"),
    (QuotaExhausted, "serialization"),
)


def _drop_field_titles(node: object) -> object:
    """Remove per-field ``title``s so generated types inline them (model titles stay)."""
    if isinstance(node, list):
        return [_drop_field_titles(item) for item in cast(list[object], node)]
    if not isinstance(node, dict):
        return node
    table = cast(dict[str, object], node)
    cleaned = {key: _drop_field_titles(value) for key, value in table.items()}
    properties = cleaned.get("properties")
    if isinstance(properties, dict):
        fields = cast(dict[str, dict[str, object]], properties)
        cleaned["properties"] = {
            name: {k: v for k, v in field.items() if k != "title"} for name, field in fields.items()
        }
    return cleaned


def contract_schema() -> dict[str, Any]:
    """Return the JSON Schema of every contract model, keyed by model name."""
    refs, top = models_json_schema(_MODELS, ref_template="#/$defs/{model}")
    properties = {model.__name__: refs[(model, mode)] for model, mode in _MODELS}
    return {
        "title": "ApiContract",
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
        "$defs": _drop_field_titles(top.get("$defs", {})),
    }


def contract_json() -> str:
    """The contract schema as stable, sorted JSON text (what is committed)."""
    return json.dumps(contract_schema(), indent=2, sort_keys=True) + "\n"
