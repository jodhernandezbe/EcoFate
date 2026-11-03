"""Embedding provider factory: the only module that imports a provider package.

Everything else in this package works with ``langchain_core.embeddings.Embeddings``,
so changing provider means adding an entry to ``_PROVIDERS`` (and to
``config.retrieval.SUPPORTED_EMBEDDING_PROVIDERS``) and editing ``[embeddings]`` in
``config/settings.toml``.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from langchain_core.embeddings import Embeddings
from pydantic import SecretStr

from config.retrieval import EmbeddingSettings
from tools.credentials import PROVIDER_KEY
from tools.emissions.rag.errors import EmbeddingError


@dataclass(frozen=True)
class _Provider:
    """How to build one provider's embeddings and which of its exceptions are expected."""

    build: Callable[[EmbeddingSettings, SecretStr], Embeddings]
    errors: Callable[[], tuple[type[Exception], ...]]


def _openai_embeddings(settings: EmbeddingSettings, api_key: SecretStr) -> Embeddings:
    from langchain_openai import OpenAIEmbeddings  # provider package: imported only here

    return OpenAIEmbeddings(
        model=settings.model,
        api_key=api_key,
        timeout=settings.timeout_seconds,
        max_retries=1,
        # Inputs are short descriptions; skip tiktoken length checks (and their download).
        check_embedding_ctx_length=False,
    )


def _openai_errors() -> tuple[type[Exception], ...]:
    import openai

    # The SDK wraps every transport failure (timeouts, connection errors) in OpenAIError.
    return (openai.OpenAIError,)


_PROVIDERS: Mapping[str, _Provider] = {
    "openai": _Provider(build=_openai_embeddings, errors=_openai_errors),
}


def _is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _check_vector(vector: object) -> list[float]:
    """Return a copy of ``vector`` if it is a non-empty list of finite numbers."""
    items = cast(list[object], vector) if isinstance(vector, list) else []
    if not items or not all(_is_finite_number(x) for x in items):
        raise EmbeddingError("provider returned an empty or non-finite vector")
    return [float(cast(float, x)) for x in items]


def _check_vectors(vectors: object, expected: int) -> list[list[float]]:
    """Return copies of the provider output if it is ``expected`` valid vectors."""
    items = cast(list[object], vectors) if isinstance(vectors, list) else None
    if items is None or len(items) != expected:
        raise EmbeddingError(f"provider returned an unexpected number of vectors ({expected} sent)")
    return [_check_vector(vector) for vector in items]


class GuardedEmbeddings(Embeddings):
    """Wrap a provider: its expected errors become ``EmbeddingError``; outputs are validated."""

    def __init__(self, inner: Embeddings, errors: tuple[type[Exception], ...]) -> None:
        self._inner = inner
        self._errors = errors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts``; raises ``EmbeddingError`` on provider failure or bad output."""
        try:
            vectors = self._inner.embed_documents(texts)
        except self._errors as exc:
            raise EmbeddingError(f"embedding request failed ({type(exc).__name__})") from exc
        return _check_vectors(vectors, len(texts))

    def embed_query(self, text: str) -> list[float]:
        """Embed one query; raises ``EmbeddingError`` on provider failure or bad output."""
        try:
            vector = self._inner.embed_query(text)
        except self._errors as exc:
            raise EmbeddingError(f"embedding request failed ({type(exc).__name__})") from exc
        return _check_vectors([vector], 1)[0]


def _resolve_key(settings: EmbeddingSettings, environ: Mapping[str, str] | None) -> SecretStr:
    """The key for this request (see ``tools.credentials``), else the environment variable's."""
    provided = PROVIDER_KEY.get()
    if provided is not None:
        return provided
    env = os.environ if environ is None else environ
    value = env.get(settings.api_key_env_var, "").strip()
    if not value:
        raise EmbeddingError(f"{settings.api_key_env_var} is not set")
    return SecretStr(value)


class _PerCallKey(Embeddings):
    """Builds the provider embeddings with the key current at each call; holds no key itself."""

    def __init__(
        self,
        build: Callable[[SecretStr], Embeddings],
        resolve: Callable[[], SecretStr],
    ) -> None:
        self._build = build
        self._resolve = resolve

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` with the current key."""
        return self._build(self._resolve()).embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed one query with the current key."""
        return self._build(self._resolve()).embed_query(text)


def build_embeddings(
    settings: EmbeddingSettings,
    environ: Mapping[str, str] | None = None,
) -> Embeddings:
    """Build the configured provider's embeddings (the outer edge for this collaborator).

    The key is resolved at every embedding call, not stored: the one provided to the current
    request (the web program's keychain key) wins, else the environment variable's.

    Args:
        settings: Provider, model, API-key variable name and timeout (seconds).
        environ: Environment the API key is read from; defaults to ``os.environ``.

    Returns:
        Guarded embeddings: provider failures surface as ``EmbeddingError``.

    Raises:
        EmbeddingError: If no key is available now (none provided and the variable unset).
        ValueError: If the provider is not supported (a configuration error).
    """

    def resolve() -> SecretStr:
        return _resolve_key(settings, environ)

    resolve()  # fail at build time when no key is available, as before
    provider = _PROVIDERS.get(settings.provider)
    if provider is None:
        raise ValueError(f"unsupported embedding provider: {settings.provider}")
    lazy = _PerCallKey(lambda key: provider.build(settings, key), resolve)
    return GuardedEmbeddings(lazy, provider.errors())


def supported_providers() -> tuple[str, ...]:
    """Names of the providers this module can build."""
    return tuple(_PROVIDERS)
