"""Unit tests for the embedding service (mocked providers)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.knowledge.embeddings.base import EmbeddingError
from apps.knowledge.embeddings.factory import get_embedding_service, reset_embedding_service
from apps.knowledge.embeddings.service import EmbeddingService


class _FakeProvider:
    model_name = "test-model"
    dimensions = 768

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.2] * 768


class _BadDimProvider(_FakeProvider):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 512 for _ in texts]


@override_settings(
    EMBEDDING_PROVIDER="local",
    EMBEDDING_MODEL="test-model",
    EMBEDDING_DIMENSIONS=768,
)
class EmbeddingServiceTests(SimpleTestCase):
    def setUp(self):
        reset_embedding_service()

    def tearDown(self):
        reset_embedding_service()

    def test_embed_many_validates_dimensions(self):
        service = EmbeddingService(_BadDimProvider())
        with self.assertRaises(EmbeddingError):
            service.embed_many(["hello"])

    def test_embed_many_returns_vectors(self):
        service = EmbeddingService(_FakeProvider())
        vectors = service.embed_many(["a", "b"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 768)

    @patch("apps.knowledge.embeddings.factory.LocalEmbeddingProvider", return_value=_FakeProvider())
    def test_factory_returns_cached_service(self, _mock_local):
        first = get_embedding_service()
        second = get_embedding_service()
        self.assertIs(first, second)
        self.assertEqual(first.model_name, "test-model")

    @override_settings(EMBEDDING_PROVIDER="unknown")
    def test_factory_rejects_unknown_provider(self):
        with self.assertRaises(EmbeddingError):
            get_embedding_service()
