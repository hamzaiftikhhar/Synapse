"""Factory for the singleton EmbeddingService."""

from __future__ import annotations

from django.conf import settings

from apps.knowledge.embeddings.base import EmbeddingError
from apps.knowledge.embeddings.local import LocalEmbeddingProvider
from apps.knowledge.embeddings.openai_provider import OpenAIEmbeddingProvider
from apps.knowledge.embeddings.service import EmbeddingService

_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return a cached EmbeddingService configured from settings."""
    global _service
    if _service is None:
        _service = EmbeddingService(_build_provider())
    return _service


def reset_embedding_service() -> None:
    """Clear cached service — for tests only."""
    global _service
    _service = None


def _build_provider():
    provider = settings.EMBEDDING_PROVIDER.lower()
    model = settings.EMBEDDING_MODEL
    dimensions = settings.EMBEDDING_DIMENSIONS

    if provider == "local":
        return LocalEmbeddingProvider(model_name=model, dimensions=dimensions)
    if provider == "openai":
        return OpenAIEmbeddingProvider(
            model_name=model,
            dimensions=dimensions,
            api_key=settings.OPENAI_API_KEY,
        )
    raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER: {settings.EMBEDDING_PROVIDER!r}")
