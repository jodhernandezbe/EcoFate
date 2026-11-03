"""Typed loaders for the ``[embeddings]`` and ``[scc_index]`` settings (SCC retrieval)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from config.parsing import (
    names,
    project_path,
    read_toml,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)

# Embedding providers the SCC retrieval can build (see ``tools/emissions/rag/embeddings.py``).
SUPPORTED_EMBEDDING_PROVIDERS = ("openai",)
SCC_COLUMN_KEYS = (
    "scc",
    "category",
    "status",
    "level_one",
    "level_two",
    "level_three",
    "level_four",
    "sector",
)
# Collection names the vector store accepts.
_COLLECTION_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]")


@dataclass(frozen=True)
class EmbeddingSettings:
    """Embedding model settings. The API key itself is never stored, only its variable name.

    Attributes:
        provider: One of ``SUPPORTED_EMBEDDING_PROVIDERS``.
        model: Provider model name, e.g. ``"text-embedding-3-small"``.
        api_key_env_var: Environment variable holding the provider API key.
        timeout_seconds: Per-request timeout, in seconds.
    """

    provider: str
    model: str
    api_key_env_var: str
    timeout_seconds: float


@dataclass(frozen=True)
class SccIndexSettings:
    """SCC vector-index settings.

    Attributes:
        source_path: SCC table (CSV), absolute or resolved against the project root.
        persist_dir: Directory holding the persisted index.
        collection: Index collection name.
        categories: ``data category`` values to index, e.g. ``("Point",)``.
        statuses: ``status`` values to index, e.g. ``("Active",)``.
        top_k: Results returned per query.
        batch_size: Documents embedded per request while indexing.
        query_cache_size: Query embeddings kept in memory, least recently used dropped.
        columns: Field (see ``SCC_COLUMN_KEYS``) -> column of the SCC table.
    """

    source_path: Path
    persist_dir: Path
    collection: str
    categories: tuple[str, ...]
    statuses: tuple[str, ...]
    top_k: int
    batch_size: int
    query_cache_size: int
    columns: Mapping[str, str]


def _provider(table: dict[str, object]) -> str:
    provider = require_str(table, "provider", "embeddings").strip().lower()
    if provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        supported = ", ".join(SUPPORTED_EMBEDDING_PROVIDERS)
        raise ValueError(f"embeddings.provider must be one of: {supported}")
    return provider


def load_embedding_settings(path: Path | None = None) -> EmbeddingSettings:
    """Load and validate the embedding model settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (timeout in seconds).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), "embeddings")
    return EmbeddingSettings(
        provider=_provider(table),
        model=require_str(table, "model", "embeddings").strip(),
        api_key_env_var=require_str(table, "api_key_env_var", "embeddings").strip(),
        timeout_seconds=require_number(table, "timeout_seconds", minimum=0.001, name="embeddings"),
    )


@lru_cache(maxsize=1)
def get_embedding_settings() -> EmbeddingSettings:
    """Return the cached embedding settings from the default file."""
    return load_embedding_settings()


def _collection(table: dict[str, object]) -> str:
    name = require_str(table, "collection", "scc_index").strip()
    if not _COLLECTION_NAME.fullmatch(name):
        raise ValueError(
            "scc_index.collection must be 3-512 characters from [a-zA-Z0-9._-], "
            "starting and ending with a letter or digit",
        )
    return name


def _scc_columns(table: dict[str, object]) -> Mapping[str, str]:
    columns = subtable(table, "columns", "scc_index")
    name = "scc_index.columns"
    return MappingProxyType({key: require_str(columns, key, name) for key in SCC_COLUMN_KEYS})


def load_scc_index_settings(path: Path | None = None) -> SccIndexSettings:
    """Load and validate the SCC vector-index settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (paths resolved against the project root).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), "scc_index")
    name = "scc_index"
    return SccIndexSettings(
        source_path=project_path(table, "source_path", name),
        persist_dir=project_path(table, "persist_dir", name),
        collection=_collection(table),
        categories=names(table, "categories", name, allow_empty=False),
        statuses=names(table, "statuses", name, allow_empty=False),
        top_k=require_int(table, "top_k", minimum=1, name=name),
        batch_size=require_int(table, "batch_size", minimum=1, name=name),
        query_cache_size=require_int(table, "query_cache_size", minimum=1, name=name),
        columns=_scc_columns(table),
    )


@lru_cache(maxsize=1)
def get_scc_index_settings() -> SccIndexSettings:
    """Return the cached SCC index settings from the default file."""
    return load_scc_index_settings()
