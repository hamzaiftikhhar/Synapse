"""Vector similarity search over indexed knowledge chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from pgvector.django import CosineDistance

from apps.clinics.models import Clinic
from apps.knowledge.embeddings import get_embedding_service
from apps.knowledge.models import Document, DocumentStatus, KnowledgeChunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimilaritySearchResult:
    score: float
    chunk: KnowledgeChunk
    document: Document


class SimilaritySearchService:
    """Clinic-scoped cosine similarity search via pgvector."""

    @classmethod
    def search(
        cls,
        *,
        clinic: Clinic,
        query: str,
        top_k: int = 5,
        document_ids: list[str] | None = None,
    ) -> list[SimilaritySearchResult]:
        """
        Embed the query, search pgvector, return top-k chunks by cosine similarity.

        Only searches chunks from indexed documents with non-null embeddings.
        Optionally scope to matching document_ids from the routing catalog.
        """
        query = query.strip()
        if not query:
            return []

        service = get_embedding_service()
        query_vector = service.embed_query(query)

        qs = KnowledgeChunk.objects.filter(
            clinic=clinic,
            embedding__isnull=False,
            document__status=DocumentStatus.INDEXED,
            document__is_deleted=False,
        )
        if document_ids:
            qs = qs.filter(document_id__in=document_ids)

        rows = (
            qs.select_related("document")
            .annotate(distance=CosineDistance("embedding", query_vector))
            .order_by("distance")[:top_k]
        )

        results: list[SimilaritySearchResult] = []
        for row in rows:
            # Cosine distance ∈ [0, 2]; similarity = 1 - distance for unit vectors.
            score = round(max(0.0, 1.0 - row.distance), 4)
            results.append(
                SimilaritySearchResult(
                    score=score,
                    chunk=row,
                    document=row.document,
                )
            )

        logger.debug(
            "Similarity search clinic=%s query=%r top_k=%s hits=%s provider=%s",
            clinic.id,
            query[:80],
            top_k,
            len(results),
            settings.EMBEDDING_PROVIDER,
        )
        return results
