"""Factory for the singleton EmbeddingService."""

from __future__ import annotations

from django.conf import settings

from apps.knowledge.embeddings.base import EmbeddingError
from apps.knowledge.embeddings.openai_provider import OpenAIEmbeddingProvider
from apps.knowledge.embeddings.service import EmbeddingService

_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return a cached EmbeddingService configured from settings."""
    global _service
    if _service is None:
        _service = EmbeddingService(_build_provider())
    return _service


def warm_up_embedding_service() -> bool:
    """Always a no-op.

    Local SentenceTransformer used to preload here so the first chat
    request did not pay a ~20s model load. OpenAI embeddings are an HTTP
    call with nothing to cache locally, so gunicorn/runserver must not
    try to import torch or download a Hugging Face model.
    """
    return False


def reset_embedding_service() -> None:
    """Clear cached service — for tests only."""
    global _service
    _service = None


def _build_provider():
    provider = settings.EMBEDDING_PROVIDER.lower()
    model = settings.EMBEDDING_MODEL
    dimensions = settings.EMBEDDING_DIMENSIONS

    if provider == "local":
        raise EmbeddingError(
            "Local SentenceTransformer embeddings were removed. "
            "Set EMBEDDING_PROVIDER=openai and EMBEDDING_MODEL="
            "text-embedding-3-small."
        )
    if provider == "openai":
        return OpenAIEmbeddingProvider(
            model_name=model,
            dimensions=dimensions,
            api_key=settings.OPENAI_API_KEY,
        )
    raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER: {settings.EMBEDDING_PROVIDER!r}")
