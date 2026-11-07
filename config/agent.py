"""Typed loader for the ``[agent]`` settings: the chat model that drives the agent."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import read_toml, require_int, require_number, require_str, section

# Chat model providers the program can build (see ``app/chat_model.py``).
SUPPORTED_CHAT_PROVIDERS = ("openai",)
_NAME = "agent"
_MAX_TEMPERATURE = 2.0  # the widest range the supported providers accept


@dataclass(frozen=True)
class AgentSettings:
    """Chat model settings. The API key itself is never stored, only its variable name.

    Attributes:
        provider: One of ``SUPPORTED_CHAT_PROVIDERS``.
        model: Provider model name, e.g. ``"gpt-4.1"``.
        api_key_env_var: Environment variable holding the provider API key.
        timeout_seconds: Per-request timeout, in seconds.
        recursion_limit: LangGraph step limit of one agent run.
        temperature: Sampling temperature, 0 (most reproducible) to 2.
        max_resumes_per_turn: How many times one interrupted turn may be resumed.
    """

    provider: str
    model: str
    api_key_env_var: str
    timeout_seconds: float
    recursion_limit: int
    temperature: float
    max_resumes_per_turn: int


def chat_provider(table: dict[str, object], key: str, name: str) -> str:
    """Return a supported chat provider name, lower-cased; raises naming ``name.key``."""
    provider = require_str(table, key, name).strip().lower()
    if provider not in SUPPORTED_CHAT_PROVIDERS:
        supported = ", ".join(SUPPORTED_CHAT_PROVIDERS)
        raise ValueError(f"{name}.{key} must be one of: {supported}")
    return provider


def _temperature(table: dict[str, object]) -> float:
    value = require_number(table, "temperature", minimum=0, name=_NAME)
    if value > _MAX_TEMPERATURE:
        raise ValueError(f"{_NAME}.temperature must be between 0 and {_MAX_TEMPERATURE}")
    return value


def load_agent_settings(path: Path | None = None) -> AgentSettings:
    """Load and validate the agent chat model settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (timeout in seconds).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    return AgentSettings(
        provider=chat_provider(table, "provider", _NAME),
        model=require_str(table, "model", _NAME).strip(),
        api_key_env_var=require_str(table, "api_key_env_var", _NAME).strip(),
        timeout_seconds=require_number(table, "timeout_seconds", minimum=0.001, name=_NAME),
        recursion_limit=require_int(table, "recursion_limit", minimum=1, name=_NAME),
        temperature=_temperature(table),
        max_resumes_per_turn=require_int(table, "max_resumes_per_turn", minimum=1, name=_NAME),
    )


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    """Return the cached agent settings from the default file."""
    return load_agent_settings()
