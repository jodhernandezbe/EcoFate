"""Persistent vector index (Chroma) that rebuilds itself when its source changes.

The only module that imports ``chromadb``. Vectors come from an injected
``langchain_core.embeddings.Embeddings``, so Chroma's own default embedder is never used
(nor downloaded). The collection metadata records the source fingerprint and the number of
documents written, so a stale or half-built index is never reused.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import chromadb
import numpy as np
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import QueryResult
from chromadb.config import Settings
from chromadb.errors import ChromaError
from langchain_core.embeddings import Embeddings

from tools.emissions.rag.errors import VectorStoreError

_FINGERPRINT_KEY = "fingerprint"
_COUNT_KEY = "expected_count"
_STORE_ERRORS = (ChromaError, sqlite3.Error, OSError)


@dataclass(frozen=True)
class IndexedDocument:
    """One document to index: unique ``id``, the ``text`` embedded, string ``metadata``."""

    id: str
    text: str
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class ScoredDocument:
    """One query hit: document ``id``, its stored ``metadata`` and a similarity ``score``.

    ``score`` is 1 - cosine distance, clipped to [0, 1] (1 = same direction).
    """

    id: str
    metadata: Mapping[str, str]
    score: float


def _string_metadata(raw: Mapping[str, object] | None) -> Mapping[str, str]:
    return MappingProxyType({k: v for k, v in (raw or {}).items() if isinstance(v, str)})


def _scored(result: QueryResult) -> list[ScoredDocument]:
    """Turn Chroma's per-query lists (first query only) into scored hits."""
    ids = result["ids"][0] if result["ids"] else []
    metadatas = (result["metadatas"] or [[]])[0]
    distances = (result["distances"] or [[]])[0]
    return [
        ScoredDocument(id=i, metadata=_string_metadata(m), score=max(0.0, min(1.0, 1.0 - d)))
        for i, m, d in zip(ids, metadatas, distances, strict=True)
    ]


class VectorIndex:
    """A named, persisted collection of embedded documents."""

    def __init__(
        self,
        persist_dir: Path,
        collection: str,
        embeddings: Embeddings,
        batch_size: int,
        query_cache_size: int,
    ) -> None:
        """Args: index directory, collection name, embeddings (injected), docs per request,
        query embeddings kept in memory."""
        self._persist_dir = persist_dir
        self._name = collection
        self._embeddings = embeddings
        self._batch_size = batch_size
        self._client: ClientAPI | None = None
        self._ready_fingerprint: str | None = None
        self._cache_size = query_cache_size
        self._vectors: OrderedDict[str, list[float]] = OrderedDict()
        self._vectors_lock = threading.Lock()

    def _open(self) -> ClientAPI:
        if self._client is None:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            settings = Settings(anonymized_telemetry=False)
            self._client = chromadb.PersistentClient(path=str(self._persist_dir), settings=settings)
        return self._client

    def _is_current(self, fingerprint: str) -> bool:
        collection = self._open().get_or_create_collection(self._name, embedding_function=None)
        metadata = collection.metadata or {}
        expected = metadata.get(_COUNT_KEY)
        return metadata.get(_FINGERPRINT_KEY) == fingerprint and collection.count() == expected

    def _add(self, collection: Collection, batch: Sequence[IndexedDocument]) -> None:
        vectors = self._embeddings.embed_documents([d.text for d in batch])
        collection.add(
            ids=[d.id for d in batch],
            embeddings=np.asarray(vectors, dtype=np.float32),
            documents=[d.text for d in batch],
            metadatas=[dict(d.metadata) for d in batch],
        )

    def _rebuild(self, fingerprint: str, documents: Sequence[IndexedDocument]) -> None:
        client = self._open()
        client.delete_collection(self._name)
        collection = client.create_collection(
            self._name,
            metadata={_FINGERPRINT_KEY: fingerprint, _COUNT_KEY: len(documents)},
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )
        for start in range(0, len(documents), self._batch_size):
            self._add(collection, documents[start : start + self._batch_size])

    def ensure(self, fingerprint: str, load: Callable[[], Sequence[IndexedDocument]]) -> bool:
        """Make the index match ``fingerprint``, rebuilding it from ``load()`` if needed.

        Returns:
            True if the index was (re)built, False if the persisted one was reused.

        Raises:
            VectorStoreError: If the store cannot be opened or written.
            Whatever ``load`` or the embeddings raise (e.g. ``SourceError``,
            ``EmbeddingError``); a half-built index is detected and rebuilt next time.
        """
        if self._ready_fingerprint == fingerprint:
            return False
        try:
            current = self._is_current(fingerprint)
            if not current:
                self._rebuild(fingerprint, load())
        except _STORE_ERRORS as exc:
            raise VectorStoreError(f"vector index {self._name} failed: {exc}") from exc
        self._ready_fingerprint = fingerprint
        return not current

    def _remember(self, text: str, vector: list[float]) -> None:
        with self._vectors_lock:
            self._vectors[text] = vector
            self._vectors.move_to_end(text)
            while len(self._vectors) > self._cache_size:
                self._vectors.popitem(last=False)

    def _remembered(self, text: str) -> list[float] | None:
        with self._vectors_lock:
            vector = self._vectors.get(text)
            if vector is not None:
                self._vectors.move_to_end(text)
            return None if vector is None else list(vector)

    def warm(self, texts: Sequence[str]) -> None:
        """Embed the queries not yet remembered in ONE request, so later queries need none.

        Raises:
            EmbeddingError: If the queries cannot be embedded.
        """
        missing = [t for t in dict.fromkeys(texts) if self._remembered(t) is None]
        for start in range(0, len(missing), self._batch_size):
            batch = missing[start : start + self._batch_size]
            for text, vector in zip(batch, self._embeddings.embed_documents(batch), strict=True):
                self._remember(text, vector)

    def _query_vector(self, text: str) -> list[float]:
        vector = self._remembered(text)
        if vector is None:
            vector = self._embeddings.embed_query(text)
            self._remember(text, vector)
        return vector

    def query(self, text: str, k: int) -> list[ScoredDocument]:
        """Return up to ``k`` documents most similar to ``text``, best first.

        Raises:
            VectorStoreError: If the store cannot be queried.
            EmbeddingError: If the query cannot be embedded.
        """
        vector = self._query_vector(text)
        try:
            collection = self._open().get_collection(self._name, embedding_function=None)
            result = collection.query(
                query_embeddings=[vector],
                n_results=k,
                include=["metadatas", "distances"],
            )
        except _STORE_ERRORS as exc:
            raise VectorStoreError(f"vector index {self._name} query failed: {exc}") from exc
        return _scored(result)
