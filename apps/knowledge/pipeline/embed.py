"""Generate embeddings via OpenAI — swappable provider module."""

from __future__ import annotations

from django.conf import settings


class EmbeddingError(Exception):
    pass


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Batch-embed texts using OpenAI text-embedding-3-small (1536 dims).

    Returns one vector per input string, in the same order.
    """
    if not texts:
        return []

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY is not configured")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise EmbeddingError("openai package is not installed") from exc

    client = OpenAI(api_key=api_key)
    model = settings.OPENAI_EMBEDDING_MODEL

    try:
        response = client.embeddings.create(
            model=model,
            input=texts,
            dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
        )
    except Exception as exc:
        raise EmbeddingError(str(exc)) from exc

    return [item.embedding for item in response.data]
