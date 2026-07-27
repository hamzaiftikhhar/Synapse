"""Local SentenceTransformer embeddings (BGE, etc.)."""

from __future__ import annotations

import logging
import threading

from apps.knowledge.embeddings.base import EmbeddingError

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_cache: dict[str, object] = {}

_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _get_sentence_transformer(model_name: str):
    """Load and cache one SentenceTransformer instance per model id."""
    if model_name in _model_cache:
        return _model_cache[model_name]

    with _model_lock:
        if model_name in _model_cache:
            return _model_cache[model_name]
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed. "
                "Add it to requirements/base.txt."
            ) from exc

        logger.info("Loading local embedding model: %s", model_name)
        model = SentenceTransformer(model_name)
        _model_cache[model_name] = model
        return model


class LocalEmbeddingProvider:
    """Hugging Face SentenceTransformer backend."""

    def __init__(self, *, model_name: str, dimensions: int) -> None:
        self.model_name = model_name
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(texts, is_query=False)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], is_query=True)[0]

    def _encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        model = _get_sentence_transformer(self.model_name)
        inputs = texts
        if is_query and "bge" in self.model_name.lower():
            inputs = [f"{_BGE_QUERY_PREFIX}{t}" for t in texts]

        try:
            vectors = model.encode(
                inputs,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbeddingError(str(exc)) from exc

        return [vector.tolist() for vector in vectors]
