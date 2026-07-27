"""Provider-agnostic embedding layer for knowledge chunks."""

from apps.knowledge.embeddings.base import EmbeddingError
from apps.knowledge.embeddings.factory import get_embedding_service
from apps.knowledge.embeddings.service import EmbeddingService

__all__ = [
    "EmbeddingError",
    "EmbeddingService",
    "get_embedding_service",
]
