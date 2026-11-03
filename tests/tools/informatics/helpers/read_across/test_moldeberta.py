"""Tests for device choice, pooling and the embedder wrapper (stub tokenizer and model)."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pytest
import torch
from transformers import BatchEncoding, PreTrainedModel, PreTrainedTokenizerBase

from config.read_across import load_read_across_settings
from tools.informatics.helpers.read_across.moldeberta import (
    MolDebertaEmbedder,
    mean_pool,
    select_device,
)

MODEL = replace(load_read_across_settings().model, embedding_width=2, max_length=7)


@pytest.mark.parametrize(
    ("mps", "cuda", "device"),
    [(True, True, "mps"), (False, True, "cuda"), (False, False, "cpu")],
)
def test_device_priority(mps: bool, cuda: bool, device: str) -> None:
    assert select_device(lambda: mps, lambda: cuda) == device


def test_mean_pool_ignores_padding_and_normalizes() -> None:
    hidden = np.array([[3.0, 0.0], [0.0, 4.0], [100.0, 100.0]])
    pooled = mean_pool(hidden, np.array([1, 1, 0]))
    assert pooled.dtype == np.float32
    assert pooled.tolist() == pytest.approx([0.6, 0.8])


def test_mean_pool_rejects_empty_mask() -> None:
    with pytest.raises(ValueError, match="no token"):
        mean_pool(np.ones((2, 2)), np.array([0, 0]))


def test_mean_pool_rejects_zero_vector() -> None:
    with pytest.raises(ValueError, match="no length"):
        mean_pool(np.zeros((2, 2)), np.array([1, 1]))


def test_mean_pool_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="tokens"):
        mean_pool(np.ones((2, 2)), np.array([1, 1, 1]))


@dataclass
class _Output:
    last_hidden_state: torch.Tensor


class _Tokenizer:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def __call__(self, smiles: str, **kwargs: object) -> BatchEncoding:
        self.kwargs = kwargs
        return BatchEncoding(
            {"input_ids": torch.tensor([[5, 6]]), "attention_mask": torch.tensor([[1, 0]])},
        )


class _Model:
    def __call__(self, **tokens: torch.Tensor) -> _Output:
        return _Output(torch.tensor([[[0.0, 2.0], [9.0, 9.0]]]))


def _embedder(tokenizer: _Tokenizer, width: int = 2) -> MolDebertaEmbedder:
    settings = replace(MODEL, embedding_width=width)
    fake_tokenizer: PreTrainedTokenizerBase = tokenizer  # type: ignore[assignment]
    fake_model: PreTrainedModel = _Model()  # type: ignore[assignment]
    return MolDebertaEmbedder(fake_tokenizer, fake_model, "cpu", settings)


def test_embedder_pools_masked_tokens() -> None:
    tokenizer = _Tokenizer()
    vector = _embedder(tokenizer)("CCO")
    assert vector.tolist() == [0.0, 1.0]
    assert tokenizer.kwargs["max_length"] == 7
    assert tokenizer.kwargs["truncation"] is True
    assert tokenizer.kwargs["padding"] is True


def test_embedder_rejects_wrong_width() -> None:
    with pytest.raises(ValueError, match="width"):
        _embedder(_Tokenizer(), width=768)("CCO")
