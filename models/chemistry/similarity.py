"""Read-across similarity: one query molecule scored against a whole catalog at once.

Every score here is dimensionless. Each function works on the full catalog matrix in one
vectorized step (no per-row Python loop).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

type Scores = NDArray[np.float64]

_MIN_UNION: float = 1e-9  # floor of the Tanimoto denominator (two empty fingerprints -> 0)
_MIN_NORM: float = 1e-12  # below this a centred vector has no usable direction


def _check_pair(query: NDArray[np.generic], catalog: NDArray[np.generic], kind: str) -> None:
    """Raise ``ValueError`` unless ``query`` is a vector and ``catalog`` a matching matrix."""
    if query.ndim != 1 or catalog.ndim != 2:
        raise ValueError(f"{kind}: query must be 1-D and catalog 2-D")
    if catalog.shape[0] == 0:
        raise ValueError(f"{kind}: catalog is empty")
    if catalog.shape[1] != query.shape[0]:
        raise ValueError(
            f"{kind}: width mismatch, query has {query.shape[0]} entries and catalog rows "
            f"have {catalog.shape[1]}",
        )


def _check_finite(values: NDArray[np.generic], kind: str) -> None:
    if not np.issubdtype(values.dtype, np.number) or np.issubdtype(values.dtype, np.bool_):
        raise ValueError(f"{kind}: values must be numbers")
    if not bool(np.all(np.isfinite(values))):
        raise ValueError(f"{kind}: values must be finite")


def _check_binary(values: NDArray[np.generic], kind: str) -> None:
    if values.dtype != np.bool_ and not bool(np.all((values == 0) | (values == 1))):
        raise ValueError(f"{kind}: fingerprint entries must be 0 or 1")


def mean_vector(catalog: NDArray[np.floating]) -> NDArray[np.float64]:
    """Arithmetic mean of a reference matrix's rows: mu = (1/N) * sum(e_i).

    Args:
        catalog: Reference embeddings, shape (N, d), dimensionless.

    Returns:
        The mean embedding, shape (d,), dimensionless. It is the centre that
        ``centered`` measures against, so it must come from the whole reference set.

    Raises:
        ValueError: If ``catalog`` is not a non-empty 2-D array of finite numbers.
    """
    if catalog.ndim != 2 or catalog.shape[0] == 0:
        raise ValueError("mean_vector: catalog must be a non-empty 2-D array")
    _check_finite(catalog, "mean_vector")
    return catalog.astype(np.float64).mean(axis=0)


def centered(values: NDArray[np.floating], mean: NDArray[np.floating]) -> NDArray[np.float64]:
    """Subtract ``mean``, then L2-normalize: the first-order isotropy correction.

    Learned embeddings occupy a narrow cone, so their raw cosines are compressed into a high,
    poorly discriminating band. Measuring directions from the centre of the reference
    distribution instead spreads them out. Centering happens before normalizing, so the
    result is a unit vector relative to ``mean``; a cosine between two such vectors is
    therefore relative to the reference distribution, not absolute.

    Args:
        values: One embedding, shape (d,), or a matrix of them, shape (N, d), dimensionless.
        mean: The reference mean embedding, shape (d,), dimensionless.

    Returns:
        The centred, L2-normalized values, same shape as ``values``, dimensionless.

    Raises:
        ValueError: If the widths differ, a value is not finite, or a vector equals ``mean``
            and so has no direction once centred.
    """
    if mean.ndim != 1:
        raise ValueError("centered: mean must be a 1-D array")
    if values.ndim not in (1, 2) or values.shape[-1] != mean.shape[0]:
        raise ValueError(
            f"centered: width mismatch, mean has {mean.shape[0]} entries and values "
            f"{values.shape[-1]}",
        )
    _check_finite(values, "centered")
    _check_finite(mean, "centered")
    shifted = values.astype(np.float64) - mean.astype(np.float64)
    norms = np.linalg.norm(shifted, axis=-1, keepdims=True)
    if not bool(np.all(norms >= _MIN_NORM)):
        raise ValueError("centered: a vector equal to the mean has no direction once centred")
    return shifted / norms


def cosine_similarities(query: NDArray[np.floating], catalog: NDArray[np.floating]) -> Scores:
    """Cosine similarity of one embedding to every catalog embedding.

    S_cos = clip(E . e_q, -1, 1); with L2-normalized vectors the dot product is the cosine.
    Both sides must already be centred on the same mean vector (see ``centered``) and
    L2-normalized, so the similarity is relative to that reference distribution.

    Args:
        query: Centred, L2-normalized query embedding, shape (d,), dimensionless.
        catalog: Centred, L2-normalized catalog embeddings, shape (N, d), dimensionless.

    Returns:
        Cosine similarity per catalog row, shape (N,), dimensionless, in [-1, 1].

    Raises:
        ValueError: If the shapes do not match, the catalog is empty or a value is not
            finite.
    """
    _check_pair(query, catalog, "cosine")
    _check_finite(query, "cosine")
    _check_finite(catalog, "cosine")
    dots = catalog.astype(np.float64) @ query.astype(np.float64)
    return np.clip(dots, -1.0, 1.0)


def tanimoto_similarities(query: NDArray[np.generic], catalog: NDArray[np.generic]) -> Scores:
    """Tanimoto (Jaccard) similarity of one bit fingerprint to every catalog fingerprint.

    S_tan = |F . f_q| / max(|F| + |f_q| - |F . f_q|, 1e-9), counting set bits.

    Args:
        query: Query fingerprint bits (0/1 or bool), shape (n_bits,).
        catalog: Catalog fingerprint bits (0/1 or bool), shape (N, n_bits).

    Returns:
        Tanimoto similarity per catalog row, shape (N,), dimensionless, in [0, 1]; 0 when
        both fingerprints have no bit set.

    Raises:
        ValueError: If the shapes do not match, the catalog is empty or an entry is not 0
            or 1.
    """
    _check_pair(query, catalog, "tanimoto")
    _check_binary(query, "tanimoto")
    _check_binary(catalog, "tanimoto")
    rows, bits = catalog.astype(np.int64), query.astype(np.int64)
    intersection = rows @ bits
    union = rows.sum(axis=1) + bits.sum() - intersection
    return intersection / np.maximum(union, _MIN_UNION)


def hybrid_scores(cosine: Scores, tanimoto: Scores, alpha: float) -> Scores:
    """Blend the two similarities: S = alpha * S_cos + (1 - alpha) * S_tan.

    Args:
        cosine: Cosine similarities, shape (N,), dimensionless.
        tanimoto: Tanimoto similarities, shape (N,), dimensionless.
        alpha: Weight of the cosine similarity, dimensionless, in [0, 1].

    Returns:
        Hybrid read-across score per catalog row, shape (N,), dimensionless.

    Raises:
        ValueError: If ``alpha`` is outside [0, 1] or the arrays differ in shape.
    """
    if isinstance(alpha, bool) or not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if cosine.shape != tanimoto.shape or cosine.ndim != 1:
        raise ValueError("cosine and tanimoto must be 1-D arrays of the same length")
    return alpha * cosine + (1.0 - alpha) * tanimoto


def best_index(scores: Scores) -> int:
    """Index of the highest score; ties go to the lowest index (the earliest row).

    Args:
        scores: Scores per catalog row, shape (N,), dimensionless.

    Raises:
        ValueError: If ``scores`` is empty, not 1-D, or holds a non-finite value.
    """
    if scores.ndim != 1 or scores.shape[0] == 0:
        raise ValueError("scores must be a non-empty 1-D array")
    _check_finite(scores, "scores")
    return int(np.argmax(scores))


def leave_one_out_scores(
    embeddings: NDArray[np.floating],
    bits: NDArray[np.generic],
    alpha: float,
) -> Scores:
    """Each catalog row's best hybrid score against every other row.

    This is how an applicability-domain threshold is calibrated: it says how close the
    chemicals of a catalog are to their own nearest neighbour, so a threshold can be read off
    a percentile of a real distribution instead of guessed.

    Args:
        embeddings: Centred, L2-normalized catalog embeddings, shape (N, d).
        bits: Catalog fingerprint bits, shape (N, n_bits).
        alpha: Weight of the cosine similarity, dimensionless, in [0, 1].

    Returns:
        One best score per row, shape (N,), dimensionless, each excluding the row itself.

    Raises:
        ValueError: If there are fewer than two rows, or the two matrices disagree on rows.
    """
    rows = embeddings.shape[0] if embeddings.ndim == 2 else 0
    if rows < 2:
        raise ValueError("leave_one_out_scores: needs at least two catalog rows")
    if bits.ndim != 2 or bits.shape[0] != rows:
        raise ValueError("leave_one_out_scores: embeddings and bits must have the same rows")
    best = np.empty(rows, dtype=np.float64)
    for row in range(rows):
        cosine = cosine_similarities(embeddings[row], embeddings)
        tanimoto = tanimoto_similarities(bits[row], bits)
        scores = hybrid_scores(cosine, tanimoto, alpha)
        scores[row] = -np.inf  # exclude the row's perfect score against itself
        best[row] = scores.max()
    return best
