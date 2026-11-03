"""Tests for the SCC retrieval graph through its public retriever."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.retrieval import load_embedding_settings
from tests.tools.emissions.rag.fakes import HEADER, INDEXED, ROWS, KeywordEmbeddings, scc_settings
from tools.emissions.rag import retriever as retriever_module
from tools.emissions.rag.errors import EmbeddingError
from tools.emissions.rag.retriever import SccRetriever, default_scc_retriever


def _retriever(tmp_path: Path, embeddings: KeywordEmbeddings, top_k: int = 5) -> SccRetriever:
    return SccRetriever(scc_settings(tmp_path, top_k=top_k), load_embedding_settings(), embeddings)


def test_refinery_description_ranks_refining_first(tmp_path: Path) -> None:
    lookup = _retriever(tmp_path, KeywordEmbeddings()).lookup("Petroleum Refineries")
    assert lookup.warnings == ()
    assert lookup.hits[0].document.scc == "99900001"
    assert lookup.hits[0].document.level_four == "Catalytic Cracking Unit"
    scores = [hit.score for hit in lookup.hits]
    assert scores == sorted(scores, reverse=True)


def test_only_point_active_codes_returned(tmp_path: Path) -> None:
    lookup = _retriever(tmp_path, KeywordEmbeddings(), top_k=10).lookup("petroleum refining")
    assert {hit.document.scc for hit in lookup.hits} == set(INDEXED)


def test_top_k_bound(tmp_path: Path) -> None:
    lookup = _retriever(tmp_path, KeywordEmbeddings(), top_k=1).lookup("chemical manufacturing")
    assert len(lookup.hits) == 1
    assert lookup.hits[0].document.scc == "99900006"


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_description_makes_no_embedding_call(tmp_path: Path, query: str) -> None:
    embeddings = KeywordEmbeddings()
    lookup = _retriever(tmp_path, embeddings).lookup(query)
    assert lookup.hits == ()
    assert lookup.warnings == ("the industry description is empty",)
    assert embeddings.document_calls == embeddings.query_calls == 0


def test_index_built_once_across_lookups(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    retriever = _retriever(tmp_path, embeddings)
    retriever.lookup("coal boiler")
    retriever.lookup("refinery")
    assert embeddings.document_calls == 2  # 3 documents, batch size 2, built once
    assert embeddings.query_calls == 2


def test_changed_table_rebuilds(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    retriever = _retriever(tmp_path, embeddings)
    retriever.lookup("coal")
    (tmp_path / "scc.csv").write_text(
        HEADER + ROWS.replace("Pulverized Coal Boiler", "Gas Turbine"),
    )
    lookup = retriever.lookup("gas turbine")
    assert embeddings.document_calls == 4
    assert lookup.hits[0].document.level_four == "Gas Turbine"


def test_embedding_failure_while_indexing_is_a_warning(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings(fail_after_documents=0)
    embeddings.error = EmbeddingError("embedding request failed (APITimeoutError)")
    lookup = _retriever(tmp_path, embeddings).lookup("refinery")
    assert lookup.hits == ()
    assert lookup.warnings == ("SCC index unavailable: embedding request failed (APITimeoutError)",)
    assert embeddings.query_calls == 0


def test_embedding_failure_while_querying_is_a_warning(tmp_path: Path) -> None:
    class QueryFails(KeywordEmbeddings):
        def embed_query(self, text: str) -> list[float]:
            raise EmbeddingError("embedding request failed (APIConnectionError)")

    lookup = _retriever(tmp_path, QueryFails()).lookup("refinery")
    assert lookup.hits == ()
    assert lookup.warnings == ("SCC search failed: embedding request failed (APIConnectionError)",)


def test_missing_table_is_a_warning(tmp_path: Path) -> None:
    retriever = _retriever(tmp_path, KeywordEmbeddings())
    (tmp_path / "scc.csv").unlink()
    lookup = retriever.lookup("refinery")
    assert lookup.hits == ()
    assert "SCC index unavailable" in lookup.warnings[0]
    assert "could not be read" in lookup.warnings[0]


def test_misconfigured_columns_raise(tmp_path: Path) -> None:
    retriever = _retriever(tmp_path, KeywordEmbeddings())
    (tmp_path / "scc.csv").write_text(HEADER.replace('"sector"', '"sectors"') + ROWS)
    with pytest.raises(ValueError, match="lacks configured columns"):
        retriever.lookup("refinery")


def test_default_retriever_needs_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(load_embedding_settings().api_key_env_var, raising=False)
    default_scc_retriever.cache_clear()
    with pytest.raises(EmbeddingError, match="is not set"):
        retriever_module.default_scc_retriever()
    default_scc_retriever.cache_clear()


class _Recording(KeywordEmbeddings):
    """Records the text that is actually embedded for each query."""

    def __init__(self) -> None:
        super().__init__()
        self.queried: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queried.append(text)
        return super().embed_query(text)


@pytest.mark.parametrize(
    "query",
    ["324110", "  325412 ", "NAICS 324110", "naics code 324-110", "code: 335999", "NAICS #324110"],
)
def test_a_bare_naics_code_is_refused_without_a_search(tmp_path: Path, query: str) -> None:
    embeddings = _Recording()
    lookup = _retriever(tmp_path, embeddings).lookup(query)
    assert lookup.hits == ()
    assert len(lookup.warnings) == 1
    assert "only a NAICS code" in lookup.warnings[0]
    assert "in words" in lookup.warnings[0]
    assert embeddings.document_calls == embeddings.query_calls == 0


@pytest.mark.parametrize(
    ("query", "searched"),
    [
        ("324110 Petroleum Refineries", "Petroleum Refineries"),
        ("NAICS 324110 - Petroleum Refineries", "Petroleum Refineries"),
        ("Petroleum Refineries (324110)", "Petroleum Refineries"),
        ("324-110 Petroleum Refineries", "Petroleum Refineries"),
        ("Petroleum Refineries", "Petroleum Refineries"),
    ],
)
def test_a_code_before_or_after_the_words_is_dropped_from_the_search(
    tmp_path: Path,
    query: str,
    searched: str,
) -> None:
    embeddings = _Recording()
    lookup = _retriever(tmp_path, embeddings).lookup(query)
    assert lookup.warnings == ()
    assert lookup.hits[0].document.scc == "99900001"
    assert embeddings.queried == [searched]


def test_digits_inside_words_are_kept(tmp_path: Path) -> None:
    embeddings = _Recording()
    _retriever(tmp_path, embeddings).lookup("3D Printing Services")
    assert embeddings.queried == ["3D Printing Services"]


def test_a_title_that_contains_a_label_word_is_kept_when_no_number_is_given(tmp_path: Path) -> None:
    embeddings = _Recording()
    _retriever(tmp_path, embeddings).lookup("Number Plate Manufacturing")
    assert embeddings.queried == ["Number Plate Manufacturing"]


def test_prefetch_embeds_the_industries_together_and_cleans_them(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings()
    retriever = _retriever(tmp_path, embeddings)
    assert (
        retriever.prefetch(["Petroleum Refineries", "324110 Petroleum Refineries", "324110"])
        is None
    )
    assert embeddings.document_calls == 1  # the code-only one is dropped, the twin shared
    retriever.lookup("Petroleum Refineries")
    assert embeddings.query_calls == 0


def test_prefetch_failure_is_a_warning_and_lookup_still_works(tmp_path: Path) -> None:
    embeddings = KeywordEmbeddings(fail_after_documents=0)
    embeddings.error = EmbeddingError("embedding request failed (APITimeoutError)")
    warning = _retriever(tmp_path, embeddings).prefetch(["Petroleum Refineries"])
    assert warning is not None and "APITimeoutError" in warning
