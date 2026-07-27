"""Thin wrapper around EmbeddingService — kept for pipeline compatibility."""

from __future__ import annotations

from apps.knowledge.embeddings import EmbeddingError, get_embedding_service

__all__ = ["EmbeddingError", "embed_texts"]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed texts using the configured provider."""
    return get_embedding_service().embed_many(texts)
