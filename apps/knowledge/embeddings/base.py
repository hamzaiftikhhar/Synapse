"""Embedding provider protocol."""

from __future__ import annotations

from typing import Protocol


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


class EmbeddingProvider(Protocol):
    """Swappable backend selected via EMBEDDING_PROVIDER."""

    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document/chunk texts for indexing."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a user search query (may use provider-specific prefixes)."""
