"""OpenAI embeddings API backend."""

from __future__ import annotations

from apps.knowledge.embeddings.base import EmbeddingError


class OpenAIEmbeddingProvider:
    """OpenAI text-embedding-* models."""

    def __init__(
        self,
        *,
        model_name: str,
        dimensions: int,
        api_key: str,
    ) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._api_key = api_key

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key:
            raise EmbeddingError("OPENAI_API_KEY is not configured")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbeddingError("openai package is not installed") from exc

        client = OpenAI(api_key=self._api_key)
        try:
            response = client.embeddings.create(
                model=self.model_name,
                input=texts,
                dimensions=self.dimensions,
            )
        except Exception as exc:
            raise EmbeddingError(str(exc)) from exc

        return [item.embedding for item in response.data]
