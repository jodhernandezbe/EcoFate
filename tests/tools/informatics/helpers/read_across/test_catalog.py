"""Tests for reading, validating and filtering the read-across catalog."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.tools.informatics.read_across_fakes import catalog_columns, settings, write_catalog
from tools.informatics.helpers.read_across.catalog import (
    BUILD_COMMAND,
    Catalog,
    filter_candidates,
    load_catalog,
)


def _load(tmp_path: Path, **extra: list[object]) -> Catalog:
    s = settings(tmp_path)
    write_catalog(s, catalog_columns(s, extra=extra))
    return load_catalog(s)


def test_loads_rows_as_read_only_matrices(tmp_path: Path) -> None:
    catalog = _load(tmp_path)
    assert catalog.cas == ("110-54-3", "71-43-2", "79-01-6")
    assert catalog.embeddings.shape == (3, 768) and catalog.embeddings.dtype == np.float32
    assert catalog.bits.shape == (3, 1024) and catalog.bits.dtype == np.uint8
    assert catalog.molecular_weights[0] == pytest.approx(86.18, abs=0.01)
    assert catalog.benchmark_flags is None and catalog.naics_prefixes is None
    for array in (catalog.embeddings, catalog.bits, catalog.molecular_weights):
        with pytest.raises(ValueError, match="read-only"):
            array[0] = 0


def test_index_of(tmp_path: Path) -> None:
    catalog = _load(tmp_path)
    assert catalog.index_of("71-43-2") == 1
    assert catalog.index_of("107-83-5") is None


def test_missing_catalog_names_location_and_command(tmp_path: Path) -> None:
    s = settings(tmp_path)
    with pytest.raises(FileNotFoundError) as error:
        load_catalog(s)
    assert str(s.directory) in str(error.value)
    assert BUILD_COMMAND in str(error.value)


def _bad(tmp_path: Path, column: str, value: list[object]) -> str:
    s = settings(tmp_path)
    columns = catalog_columns(s)
    columns[getattr(s.columns, column)] = value
    write_catalog(s, columns)
    with pytest.raises(ValueError) as error:
        load_catalog(s)
    return str(error.value)


def test_missing_column(tmp_path: Path) -> None:
    s = settings(tmp_path)
    columns = catalog_columns(s)
    del columns[s.columns.bits]
    write_catalog(s, columns)
    with pytest.raises(ValueError, match="'morgan_bits' is missing"):
        load_catalog(s)


def test_wrong_embedding_width(tmp_path: Path) -> None:
    assert "768" in _bad(tmp_path, "embedding", [[1.0, 0.0]] * 3)


def test_non_finite_embedding(tmp_path: Path) -> None:
    row = [float("nan")] + [0.0] * 767
    assert "finite" in _bad(tmp_path, "embedding", [row] * 3)


def test_non_binary_bits(tmp_path: Path) -> None:
    assert "0 and 1" in _bad(tmp_path, "bits", [[2] * 1024] * 3)


@pytest.mark.parametrize("weights", [[86.2, 0.0, 131.4], [86.2, -1.0, 131.4], [86.2, None, 1.0]])
def test_bad_weight(tmp_path: Path, weights: list[object]) -> None:
    assert "greater than zero" in _bad(tmp_path, "molecular_weight", weights)


def test_blank_cas(tmp_path: Path) -> None:
    assert "non-empty text" in _bad(tmp_path, "cas", ["110-54-3", " ", "79-01-6"])


def test_repeated_cas(tmp_path: Path) -> None:
    assert "repeated" in _bad(tmp_path, "cas", ["110-54-3", "110-54-3", "79-01-6"])


def test_flags_must_be_booleans(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="true or false"):
        _load(tmp_path, has_iris_benchmark=[1, 0, 1])


def test_naics_must_be_text_lists(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="lists of text"):
        _load(tmp_path, naics_prefixes=[[325], None, [31]])


def test_benchmark_filter(tmp_path: Path) -> None:
    catalog = _load(tmp_path, has_iris_benchmark=[False, True, False])
    candidates, warnings = filter_candidates(catalog, require_benchmarks=True, naics_prefix=None)
    assert candidates.cas == ("71-43-2",)
    assert candidates.embeddings.shape == (1, 768)
    assert not candidates.embeddings.flags.writeable
    assert warnings == []


def test_benchmark_filter_without_column(tmp_path: Path) -> None:
    catalog = _load(tmp_path)
    candidates, warnings = filter_candidates(catalog, require_benchmarks=True, naics_prefix=None)
    assert candidates.cas == catalog.cas
    assert len(warnings) == 1 and "no column" in warnings[0]


def test_benchmark_filter_matching_nothing_falls_back(tmp_path: Path) -> None:
    catalog = _load(tmp_path, has_iris_benchmark=[False, False, False])
    candidates, warnings = filter_candidates(catalog, require_benchmarks=True, naics_prefix=None)
    assert candidates.cas == catalog.cas
    assert "matched no chemical" in warnings[0]


def test_naics_filter_matches_prefix(tmp_path: Path) -> None:
    catalog = _load(tmp_path, naics_prefixes=[["325110"], ["324"], None])
    candidates, warnings = filter_candidates(catalog, require_benchmarks=False, naics_prefix="325")
    assert candidates.cas == ("110-54-3",)
    assert warnings == []


def test_naics_filter_matching_nothing_falls_back(tmp_path: Path) -> None:
    catalog = _load(tmp_path, naics_prefixes=[["325"], ["324"], None])
    candidates, warnings = filter_candidates(catalog, require_benchmarks=False, naics_prefix="11")
    assert candidates.cas == catalog.cas
    assert "NAICS '11'" in warnings[0] and "all candidates" in warnings[0]


def test_naics_filter_without_column(tmp_path: Path) -> None:
    catalog = _load(tmp_path)
    _, warnings = filter_candidates(catalog, require_benchmarks=False, naics_prefix="325")
    assert "no column" in warnings[0]


def test_blank_naics_prefix_is_no_filter(tmp_path: Path) -> None:
    catalog = _load(tmp_path)
    candidates, warnings = filter_candidates(catalog, require_benchmarks=False, naics_prefix=" ")
    assert candidates.cas == catalog.cas and warnings == []


def test_mean_and_centred_embeddings_are_derived_on_load(tmp_path: Path) -> None:
    catalog = _load(tmp_path)
    assert catalog.mean_embedding.shape == (768,)
    expected = catalog.embeddings.astype(np.float64).mean(axis=0)
    assert catalog.mean_embedding.tolist() == pytest.approx(expected.tolist())
    assert catalog.centered_embeddings.shape == (3, 768)
    norms = np.linalg.norm(catalog.centered_embeddings, axis=1)
    assert norms.tolist() == pytest.approx([1.0, 1.0, 1.0])
    for array in (catalog.mean_embedding, catalog.centered_embeddings):
        with pytest.raises(ValueError, match="read-only"):
            array[0] = 0


def test_stored_embeddings_stay_uncentered(tmp_path: Path) -> None:
    """The correction is applied on load, so the file can be reused without a rebuild."""
    s = settings(tmp_path)
    written = catalog_columns(s)[s.columns.embedding]
    catalog = _load(tmp_path)
    assert catalog.embeddings[1].tolist() == pytest.approx(written[1])  # type: ignore[arg-type]


def test_subset_keeps_the_whole_catalogs_mean(tmp_path: Path) -> None:
    catalog = _load(tmp_path, has_iris_benchmark=[False, True, False])
    candidates, _ = filter_candidates(catalog, require_benchmarks=True, naics_prefix=None)
    assert candidates.mean_embedding.tolist() == catalog.mean_embedding.tolist()
    assert candidates.centered_embeddings.shape == (1, 768)
    assert candidates.centered_embeddings[0].tolist() == pytest.approx(
        catalog.centered_embeddings[1].tolist(),
    )


def test_one_chemical_catalog_is_rejected(tmp_path: Path) -> None:
    s = settings(tmp_path)
    columns = catalog_columns(s, chemicals=(("110-54-3", "n-Hexane", "CCCCCC"),))
    write_catalog(s, columns)
    with pytest.raises(ValueError, match="at least 2 are needed"):
        load_catalog(s)
