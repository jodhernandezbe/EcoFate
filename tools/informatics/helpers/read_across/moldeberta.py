"""SMILES -> MolDeBERTa embedding (mean-pooled, L2-normalized).

The only module that imports ``torch`` and ``transformers``, and only when the default
embedder is first built; everything else takes a ``SmilesEmbedder`` injected.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from config.read_across import ModelSettings

if TYPE_CHECKING:
    import torch
    from transformers import PreTrainedModel, PreTrainedTokenizerBase

_MIN_NORM = 1e-12


class SmilesEmbedder(Protocol):
    """Turns one SMILES into an L2-normalized float32 vector of a fixed width."""

    def __call__(self, smiles: str) -> NDArray[np.float32]:
        """Return the embedding of ``smiles``."""
        ...


def select_device(mps: Callable[[], bool], cuda: Callable[[], bool]) -> str:
    """Return the first available device: Apple Silicon ("mps"), then "cuda", then "cpu"."""
    if mps():
        return "mps"
    if cuda():
        return "cuda"
    return "cpu"


def mean_pool(hidden: NDArray[np.floating], mask: NDArray[np.integer]) -> NDArray[np.float32]:
    """Average the token vectors the attention mask keeps, then L2-normalize.

    Args:
        hidden: Last hidden state of one sequence, shape (tokens, width).
        mask: Attention mask, shape (tokens,); 1 for real tokens, 0 for padding.

    Returns:
        The pooled vector, shape (width,), float32, with unit length.

    Raises:
        ValueError: If the shapes do not match, no token is kept, or the result has no
            length (a zero vector cannot be normalized).
    """
    if hidden.ndim != 2 or mask.shape != (hidden.shape[0],):
        raise ValueError("hidden must be (tokens, width) and mask (tokens,)")
    weights = mask.astype(np.float64)
    if weights.sum() == 0:
        raise ValueError("the attention mask keeps no token")
    pooled = (hidden.astype(np.float64) * weights[:, None]).sum(axis=0) / weights.sum()
    norm = float(np.linalg.norm(pooled))
    if not np.isfinite(norm) or norm < _MIN_NORM:
        raise ValueError("the pooled embedding has no length")
    return (pooled / norm).astype(np.float32)


class MolDebertaEmbedder:
    """Embeds SMILES with a Hugging Face DeBERTa encoder, one molecule at a time."""

    def __init__(
        self,
        tokenizer: PreTrainedTokenizerBase,
        model: PreTrainedModel,
        device: str,
        settings: ModelSettings,
    ) -> None:
        """Wrap a loaded tokenizer and model (in eval mode) on ``device``."""
        self._tokenizer = tokenizer
        self._model = model
        self._device = device
        self._settings = settings

    def __call__(self, smiles: str) -> NDArray[np.float32]:
        """Return the embedding of ``smiles``, shape (embedding_width,).

        Raises:
            ValueError: If the model's width is not the configured one (a setup error).
        """
        import torch

        tokens = self._tokenizer(
            smiles,
            max_length=self._settings.max_length,
            truncation=True,
            padding=True,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            hidden: torch.Tensor = self._model(**tokens).last_hidden_state
        mask: torch.Tensor = tokens["attention_mask"]
        vector = mean_pool(hidden[0].float().cpu().numpy(), mask[0].cpu().numpy())
        if vector.shape != (self._settings.embedding_width,):
            raise ValueError(
                f"model {self._settings.name} gives width {vector.shape[0]}, "
                f"configured {self._settings.embedding_width}",
            )
        return vector


@lru_cache(maxsize=1)
def default_embedder(settings: ModelSettings) -> MolDebertaEmbedder:
    """Download (first time) and load the configured model once per process.

    Raises:
        OSError: If the model cannot be downloaded or read (for example, offline on first
            use); this is a setup error.
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    device = select_device(torch.backends.mps.is_available, torch.cuda.is_available)
    # The Auto* factories are untyped; they return these base classes.
    tokenizer = cast(
        "PreTrainedTokenizerBase",
        AutoTokenizer.from_pretrained(settings.name, revision=settings.revision),
    )
    model = cast(
        "PreTrainedModel",
        AutoModel.from_pretrained(settings.name, revision=settings.revision),
    )
    model.eval()
    torch.nn.Module.to(model, torch.device(device))  # in place; the model's own .to is untyped
    return MolDebertaEmbedder(tokenizer, model, device, settings)


def lazy_default_embedder(settings: ModelSettings) -> SmilesEmbedder:
    """The default embedder, loaded on its first call (a direct match never loads it)."""

    def embed(smiles: str) -> NDArray[np.float32]:
        return default_embedder(settings)(smiles)

    return embed
