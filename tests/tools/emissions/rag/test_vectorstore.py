"""Tests for the persistent vector index."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from tests.tools.emissions.rag.fakes import KeywordEmbeddings
from tools.emissions.rag.errors import EmbeddingError
from tools.emissions.rag.vectorstore import IndexedDocument, VectorIndex

DOCUMENTS = [
    IndexedDocument(id="a", text="petroleum refining unit", metadata=MappingProxyType({"k": "1"})),
    IndexedDocument(id="b", text="coal boiler electric", metadata=MappingProxyType({"k": "2"})),
    IndexedDocument(id="c", text="chemical reactor", metadata=MappingProxyType({"k": "3"})),
]


def _index(tmp_path: Path, embeddings: KeywordEmbeddings) -> VectorIndex:
    return VectorIndex(
        tmp_path / "idx",
        "test_collection",
        embeddings,
        batch_size=2,
        query_cache_size=2,
    )


def test_build_then_reuse_in_process_and_on_disk(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    loads: list[int] = []

    def load() -> list[IndexedDocument]:
        loads.append(1)
        return DOCUMENTS

    index = _index(tmp_path, embeddings)
    assert index.ensure("fp1", load) is True
    assert embeddings.document_calls == 2  # 3 documents in batches of 2
    assert index.ensure("fp1", load) is False
    reopened = _index(tmp_path, KeywordEmbeddings())
    assert reopened.ensure("fp1", load) is False  # persisted index reused, nothing embedded
    assert loads == [1]


def test_changed_fingerprint_rebuilds(tmp_path: Path) -> None:
    index = _index(tmp_path, KeywordEmbeddings())
    index.ensure("fp1", lambda: DOCUMENTS)
    assert index.ensure("fp2", lambda: DOCUMENTS[:1]) is True
    assert [hit.id for hit in index.query("refining coal chemical", 5)] == ["a"]


def test_half_built_index_is_rebuilt(tmp_path: Path) -> None:
    failing = KeywordEmbeddings(fail_after_documents=1)
    failing.error = EmbeddingError("provider down")
    with pytest.raises(EmbeddingError):
        _index(tmp_path, failing).ensure("fp1", lambda: DOCUMENTS)
    healthy = KeywordEmbeddings()
    assert _index(tmp_path, healthy).ensure("fp1", lambda: DOCUMENTS) is True
    assert healthy.document_calls == 2


def test_query_ranked_with_scores_and_metadata(tmp_path: Path) -> None:
    index = _index(tmp_path, KeywordEmbeddings())
    index.ensure("fp1", lambda: DOCUMENTS)
    hits = index.query("petroleum refining", 2)
    assert [hit.id for hit in hits] == ["a", hits[1].id]
    assert len(hits) == 2
    assert hits[0].metadata == {"k": "1"}
    assert 0.0 <= hits[1].score <= hits[0].score <= 1.0
    assert hits[0].score > 0.5


def test_warm_embeds_the_queries_together_and_queries_then_need_no_request(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    index = _index(tmp_path, embeddings)
    index.ensure("fp1", lambda: DOCUMENTS)
    before = embeddings.document_calls
    index.warm(["petroleum refining", "coal boiler", "petroleum refining"])
    assert embeddings.document_calls == before + 1  # one request for both distinct queries
    assert [h.id for h in index.query("petroleum refining", 1)] == ["a"]
    assert [h.id for h in index.query("coal boiler", 1)] == ["b"]
    assert embeddings.query_calls == 0


def test_a_repeated_query_is_embedded_once(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    index = _index(tmp_path, embeddings)
    index.ensure("fp1", lambda: DOCUMENTS)
    index.query("chemical reactor", 1)
    index.query("chemical reactor", 1)
    assert embeddings.query_calls == 1


def test_the_query_cache_drops_the_least_recently_used(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    index = _index(tmp_path, embeddings)  # remembers 2 queries
    index.ensure("fp1", lambda: DOCUMENTS)
    for text in ("chemical reactor", "coal boiler", "petroleum refining"):
        index.query(text, 1)
    index.query("chemical reactor", 1)  # was dropped: embedded again
    assert embeddings.query_calls == 4


def test_warm_failure_raises_and_remembers_nothing(tmp_path: Path) -> None:
    failing = KeywordEmbeddings(fail_after_documents=0)
    failing.error = EmbeddingError("provider down")
    index = _index(tmp_path, failing)
    with pytest.raises(EmbeddingError):
        index.warm(["coal boiler"])
    assert index._remembered("coal boiler") is None  # pyright: ignore[reportPrivateUsage]
