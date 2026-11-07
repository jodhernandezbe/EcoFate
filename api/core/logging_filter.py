"""The server's log configuration: uvicorn's handlers routed through the redaction filter.

The filter itself lives in ``app.redaction`` (every front end of the program shares it); its
names are re-exported here for the web layer.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from app.redaction import (
    LITERAL_REDACTED,
    REDACTED,
    SecretRedactionFilter,
    install_redaction,
    protect_secrets,
    redact,
)

__all__ = [
    "LITERAL_REDACTED",
    "REDACTED",
    "SecretRedactionFilter",
    "install_redaction",
    "protect_secrets",
    "redact",
    "uvicorn_log_config",
]


def uvicorn_log_config(base: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of uvicorn's ``log_config`` with the filter on every handler.

    The root logger is routed through uvicorn's default (stderr) handler too, so application
    loggers such as ``api.agent_runner`` are shown, and redacted, instead of falling through
    to Python's unfiltered last-resort handler.
    """
    config: dict[str, Any] = copy.deepcopy(dict(base))
    config.setdefault("filters", {})["redact_secrets"] = {"()": SecretRedactionFilter}
    for handler in config.get("handlers", {}).values():
        handler.setdefault("filters", []).append("redact_secrets")
    config["root"] = {"handlers": ["default"], "level": "INFO"}
    return config
