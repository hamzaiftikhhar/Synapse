"""Integration tests for pgvector similarity search (mocked embeddings)."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.clinics.models import Clinic
from apps.knowledge.models import Document, DocumentStatus, KnowledgeChunk
from apps.knowledge.services.similarity_search import SimilaritySearchService


_DIM = 1536


class _FakeProvider:
    model_name = "test-model"
    dimensions = _DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * _DIM for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        query = text.lower()
        vector = [0.0] * _DIM
        if "diabetes" in query:
            vector[0] = 1.0
        elif "blood pressure" in query or "hypertension" in query:
            vector[1] = 1.0
        elif "insurance" in query:
            vector[2] = 1.0
        elif "appointment" in query or "book" in query:
            vector[3] = 1.0
        return vector


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * _DIM
    vector[index] = 1.0
    return vector


@override_settings(
    EMBEDDING_PROVIDER="openai",
    EMBEDDING_MODEL="test-model",
    EMBEDDING_DIMENSIONS=_DIM,
)
class SimilaritySearchTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="test-clinic",
            name="Test Clinic",
            email="test@clinic.com",
        )
        self.document = Document.objects.create(
            clinic=self.clinic,
            title="Health Guide",
            file_name="health.pdf",
            file_type="application/pdf",
            storage_path="health.pdf",
            status=DocumentStatus.INDEXED,
            chunk_count=4,
        )
        samples = [
            ("Diabetes is a chronic condition affecting blood sugar.", 0),
            ("Hypertension means high blood pressure over time.", 1),
            ("We accept Blue Cross and Aetna insurance plans.", 2),
            ("Book an appointment online or call the front desk.", 3),
        ]
        for number, (content, axis) in enumerate(samples, start=1):
            KnowledgeChunk.objects.create(
                clinic=self.clinic,
                document=self.document,
                chunk_number=number,
                content=content,
                embedding=_unit_vector(axis),
                embedding_model="test-model",
            )

    @patch("apps.knowledge.services.similarity_search.get_embedding_service")
    def test_diabetes_query_retrieves_diabetes_chunk(self, mock_get_service):
        mock_get_service.return_value = type("S", (), {"embed_query": _FakeProvider().embed_query})()
        hits = SimilaritySearchService.search(
            clinic=self.clinic,
            query="What is diabetes?",
            top_k=1,
        )
        self.assertEqual(len(hits), 1)
        self.assertIn("Diabetes", hits[0].chunk.content)
        self.assertGreater(hits[0].score, 0.9)

    @patch("apps.knowledge.services.similarity_search.get_embedding_service")
    def test_insurance_query_retrieves_insurance_chunk(self, mock_get_service):
        mock_get_service.return_value = type("S", (), {"embed_query": _FakeProvider().embed_query})()
        hits = SimilaritySearchService.search(
            clinic=self.clinic,
            query="Insurance accepted?",
            top_k=1,
        )
        self.assertEqual(len(hits), 1)
        self.assertIn("insurance", hits[0].chunk.content.lower())

    @patch("apps.knowledge.services.similarity_search.get_embedding_service")
    def test_appointment_query_retrieves_appointment_chunk(self, mock_get_service):
        mock_get_service.return_value = type("S", (), {"embed_query": _FakeProvider().embed_query})()
        hits = SimilaritySearchService.search(
            clinic=self.clinic,
            query="Book appointment",
            top_k=1,
        )
        self.assertEqual(len(hits), 1)
        self.assertIn("appointment", hits[0].chunk.content.lower())
