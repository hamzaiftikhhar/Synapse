"""Embedding service — single entry point for indexing and search."""

from __future__ import annotations

from django.conf import settings

from apps.knowledge.embeddings.base import EmbeddingError, EmbeddingProvider


class EmbeddingService:
    """
    Application-facing embedding API.

    Callers use this class only — never import SentenceTransformer or OpenAI.
    """

    def __init__(self, provider: EmbeddingProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return settings.EMBEDDING_PROVIDER

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    @property
    def dimensions(self) -> int:
        return self._provider.dimensions

    def embed(self, text: str) -> list[float]:
        """Embed one chunk/document string for storage."""
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed chunk texts for indexing."""
        if not texts:
            return []
        vectors = self._provider.embed_documents(texts)
        self._validate_vectors(vectors)
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """Embed a user search query."""
        vector = self._provider.embed_query(query)
        self._validate_vectors([vector])
        return vector

    def _validate_vectors(self, vectors: list[list[float]]) -> None:
        expected = settings.EMBEDDING_DIMENSIONS
        for index, vector in enumerate(vectors):
            if vector is None:
                raise EmbeddingError(f"Embedding {index} is null")
            if len(vector) != expected:
                raise EmbeddingError(
                    f"Embedding {index} has {len(vector)} dimensions; "
                    f"expected {expected}"
                )
