"""Pluggable text embeddings for the policy index.

Policy documents (LCD/NCD, commercial policies) are PUBLIC — they contain no PHI
— so any embedding provider is safe here. Never embed chart/PHI text through a
non-BAA provider.

Providers:
  * ``hash`` — a deterministic, offline feature-hashing embedder. No downloads,
    no network; gives real lexical-overlap similarity so pgvector retrieval works
    in dev and tests. This is the default.
  * ``sentence-transformers`` / ``voyage`` — real semantic models, wired in for
    production (documented; not required for Phase 0).

The output dimension is ``RCM_EMBEDDING_DIM`` (default 1536, matching the
``policy_doc.embedding`` column).
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from rcm.core.config import get_settings

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _hash_embed(text: str, dim: int) -> list[float]:
    """Deterministic feature-hashing embedding with L2 normalization."""
    vec = [0.0] * dim
    for tok in _tokens(text):
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


class Embedder:
    """Embeds public policy text into fixed-dimension vectors."""

    def __init__(self, provider: str | None = None, dim: int | None = None) -> None:
        settings = get_settings()
        self.provider = provider or settings.embedding_provider
        self.dim = dim or settings.embedding_dim

    def embed(self, text: str) -> list[float]:
        if self.provider == "hash":
            return _hash_embed(text, self.dim)
        raise NotImplementedError(
            f"embedding provider {self.provider!r} not wired in this build; "
            "use 'hash' for dev, or add the sentence-transformers/voyage client"
        )

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return Embedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors (for offline retrieval sanity checks)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
