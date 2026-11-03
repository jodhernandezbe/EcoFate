"""Chat model factory: the only module that imports a chat provider package.

The program and the evaluations both build the agent's model here from ``[agent]`` in
``config/settings.toml``, so they always run the same model. A new provider is an entry in
``_PROVIDERS`` plus ``config.agent.SUPPORTED_CHAT_PROVIDERS``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from config.agent import AgentSettings


def _openai_chat(
    model: str,
    api_key: SecretStr,
    timeout_seconds: float,
    temperature: float | None,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI  # provider package: imported only here

    if temperature is None:  # the provider's own default
        return ChatOpenAI(model=model, api_key=api_key, timeout=timeout_seconds)
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        timeout=timeout_seconds,
        temperature=temperature,
    )


_PROVIDERS: Mapping[str, Callable[[str, SecretStr, float, float | None], BaseChatModel]] = {
    "openai": _openai_chat,
}


def build_named_chat_model(
    provider: str,
    model: str,
    api_key_env_var: str,
    timeout_seconds: float,
    environ: Mapping[str, str] | None = None,
    *,
    temperature: float | None = None,
    api_key: SecretStr | None = None,
) -> BaseChatModel:
    """Build ``model`` of ``provider`` with ``api_key``, or the key in ``api_key_env_var``.

    ``temperature`` None leaves the provider's default (some models accept no other value).
    An injected ``api_key`` (from the OS key vault) is used as is and the environment is not
    read; the key is never unwrapped here.

    Raises:
        RuntimeError: If no key is injected and the API-key environment variable is unset or blank.
        ValueError: If the provider is not supported (a configuration error).
    """
    build = _PROVIDERS.get(provider)
    if build is None:
        raise ValueError(f"unsupported chat provider: {provider}")
    key = api_key if api_key is not None else _env_key(api_key_env_var, environ)
    return build(model, key, timeout_seconds, temperature)


def _env_key(api_key_env_var: str, environ: Mapping[str, str] | None) -> SecretStr:
    env = os.environ if environ is None else environ
    value = env.get(api_key_env_var, "").strip()
    if not value:
        raise RuntimeError(f"{api_key_env_var} is not set")
    return SecretStr(value)


def build_chat_model(
    settings: AgentSettings,
    environ: Mapping[str, str] | None = None,
    *,
    api_key: SecretStr | None = None,
) -> BaseChatModel:
    """Build the agent's chat model from the ``[agent]`` settings (the outer edge).

    Args:
        settings: Provider, model, API-key variable name, timeout (seconds) and temperature.
        environ: Environment the API key is read from; defaults to ``os.environ``.
        api_key: Key injected from the OS key vault; when given, the environment is not read.

    Raises:
        RuntimeError: If no key is injected and the API-key variable is unset or blank.
        ValueError: If the provider is not supported.
    """
    return build_named_chat_model(
        settings.provider,
        settings.model,
        settings.api_key_env_var,
        settings.timeout_seconds,
        environ,
        temperature=settings.temperature,
        api_key=api_key,
    )
