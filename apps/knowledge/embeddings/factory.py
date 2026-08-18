"""Factory for the singleton EmbeddingService."""

from __future__ import annotations

import logging

from django.conf import settings

from apps.knowledge.embeddings.base import EmbeddingError
from apps.knowledge.embeddings.local import LocalEmbeddingProvider
from apps.knowledge.embeddings.openai_provider import OpenAIEmbeddingProvider
from apps.knowledge.embeddings.service import EmbeddingService

logger = logging.getLogger(__name__)

_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return a cached EmbeddingService configured from settings."""
    global _service
    if _service is None:
        _service = EmbeddingService(_build_provider())
    return _service


def warm_up_embedding_service() -> bool:
    """Load the embedding model now instead of on the first real query.

    Only meaningful for the local SentenceTransformer provider — it lazily
    loads its model (+first-encode cost) on first use, which previously
    landed on whichever request happened to run the first vector search
    after process start. The openai provider has no such cost and is a
    no-op here. Never raises: a warm-up failure (e.g. model not cached,
    no network) just means the existing lazy-load path pays the cost on
    first real use instead, exactly as it did before this existed.

    Returns True if a model load was actually attempted (for logging/tests).
    """
    if settings.EMBEDDING_PROVIDER.lower() != "local":
        return False
    try:
        get_embedding_service().embed_query("warm up")
    except Exception:
        logger.exception("Embedding model warm-up failed — first real query will load it instead")
    return True


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
