"""Sentence embeddings for hybrid retrieval (docs/ARCHITECTURE.md §8.5): bge-small-en-v1.5 through fastembed.

ONNX on the CPU (about 70 ms per 30 s passage, M6e measurement), 384 dimensions, cached in models/fastembed by
setup.ps1 and always loaded offline, so demo day never downloads anything. If the model can't be loaded,
`get()` returns None and retrieval silently falls back to keyword search (BM25).
"""

from __future__ import annotations

import os
import threading

import numpy as np

from common.config import ROOT

MODEL = "BAAI/bge-small-en-v1.5"
CACHE = ROOT / "models" / "fastembed"
DIM = 384
_lock = threading.Lock()
_model = None
_failed = False


class Embedder:
    def __init__(self, model) -> None:
        self.model = model

    def passages(self, texts: list[str]) -> np.ndarray:
        """Unit-length float32 vectors, one row per text."""
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        return _unit(np.array(list(self.model.embed(texts, batch_size=32)), dtype=np.float32))

    def query(self, text: str) -> np.ndarray:
        """bge expects queries with its retrieval instruction; fastembed's query_embed adds it."""
        return _unit(np.array(list(self.model.query_embed(text)), dtype=np.float32))[0]


def _unit(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


def get() -> Embedder | None:
    """The process-wide embedder, or None if it can't be loaded (never raises)."""
    global _model, _failed
    with _lock:
        if _model is None and not _failed:
            try:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")              # never download at run time
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from fastembed import TextEmbedding
                _model = Embedder(TextEmbedding(MODEL, cache_dir=str(CACHE)))
            except Exception:  # noqa: BLE001 - missing package or model: keyword search still works
                _failed = True
        return _model


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blobs(blobs: list[bytes]) -> np.ndarray:
    if not blobs:
        return np.zeros((0, DIM), dtype=np.float32)
    return np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(blobs), -1)
