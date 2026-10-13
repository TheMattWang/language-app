"""Residual-stream capture for any mlx-lm decoder.

Swaps each transformer block in `model.layers` for a thin wrapper that
records the block's output -- the residual stream after layer i -- then
calls through unchanged. No forked model code, so it works for Qwen,
Gemma, Llama, ... whatever mlx-lm can load.
"""

from __future__ import annotations

import mlx.core as mx
import numpy as np
from mlx_lm import load


class _Tap:
    """Stands in for one block; records what the block returns."""

    def __init__(self, block, store: list):
        self.block, self.store = block, store

    def __call__(self, *args, **kwargs):
        out = self.block(*args, **kwargs)
        self.store.append(out[0] if isinstance(out, tuple) else out)
        return out

    def __getattr__(self, name):  # anything else the model asks of the block
        return getattr(self.block, name)


def _find_layers(model):
    """The list of transformer blocks, wherever this architecture keeps it."""
    for path in ("model.layers", "language_model.model.layers", "layers"):
        obj = model
        try:
            for part in path.split("."):
                obj = getattr(obj, part)
        except AttributeError:
            continue
        if isinstance(obj, list) and obj:
            return obj
    raise AttributeError("couldn't find the transformer blocks on this model")


class Capture:
    def __init__(self, repo: str):
        self.model, self.tokenizer = load(repo)
        self.layers = _find_layers(self.model)
        self.n_layers = len(self.layers)
        self._store: list = []
        for i, block in enumerate(self.layers):
            self.layers[i] = _Tap(block, self._store)

    def tokens(self, text: str) -> list[int]:
        return self.tokenizer.encode(text)

    def run(self, text: str) -> np.ndarray:
        """Residual stream after every block: array [n_layers, n_tokens, d_model]."""
        self._store.clear()
        ids = mx.array(self.tokens(text))[None]
        self.model(ids)
        acts = mx.stack([a[0] for a in self._store])  # drop batch dim
        mx.eval(acts)
        return np.array(acts.astype(mx.float32))

    def pooled_and_logprobs(
        self, text: str, layers: list[int] | None = None, skip_first: int = 1
    ) -> tuple[np.ndarray, np.ndarray]:
        """One forward pass: per-layer mean-pooled residual [len(layers), d]
        (float16, to keep thousands of sentences in RAM) and the log-prob the
        model gave each actual next token [n_tokens - 1]."""
        self._store.clear()
        ids = mx.array(self.tokens(text))[None]
        logits = self.model(ids)[0].astype(mx.float32)
        logp = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        token_logp = mx.take_along_axis(logp[:-1], ids[0, 1:, None], axis=-1)[:, 0]
        keep = layers if layers is not None else range(len(self._store))
        pooled = mx.stack([self._store[i][0, skip_first:].mean(axis=0) for i in keep])
        mx.eval(pooled, token_logp)
        return np.array(pooled.astype(mx.float16)), np.array(token_logp)

    def mean_pooled(self, text: str, skip_first: int = 1) -> np.ndarray:
        """Per-layer mean over tokens, skipping BOS-like positions: [n_layers, d_model].

        The first position is an attention sink with a huge norm in most
        models; leaving it in would make every sentence look alike.
        """
        acts = self.run(text)
        return acts[:, skip_first:, :].mean(axis=1)
