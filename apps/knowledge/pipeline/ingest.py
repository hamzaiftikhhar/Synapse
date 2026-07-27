"""Orchestrate document ingestion: extract → clean → chunk → (optional embed) → persist.

Why this file exists
--------------------
Each pipeline step lives in its own module. This file only wires them
in order and updates Document status.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from apps.knowledge.models import Document, DocumentStatus, KnowledgeChunk
from apps.knowledge.pipeline import chunk, clean, extract
from apps.knowledge.pipeline.extract import PageText
from apps.knowledge.services import storage

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


def ingest_document(
    document: Document,
    *,
    run_embeddings: bool | None = None,
) -> Document:
    """
    Run the pipeline for one Document row.

    Phase 2 default (KNOWLEDGE_RUN_EMBEDDINGS=False):
      extract → clean → chunk → save KnowledgeChunk rows (embedding=NULL)
      status → chunked

    Phase 3+ (KNOWLEDGE_RUN_EMBEDDINGS=True):
      … → embed → save vectors → status → indexed
    """
    if run_embeddings is None:
        run_embeddings = settings.KNOWLEDGE_RUN_EMBEDDINGS

    file_path = storage.absolute_path(document.storage_path)
    if not file_path.is_file():
        _fail(document, f"File not found: {document.storage_path}")
        raise IngestionError(document.error_message)

    document.status = DocumentStatus.PROCESSING
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])

    try:
        raw_pages = extract.extract_pages(
            file_path=file_path, file_type=document.file_type
        )
        cleaned_pages: list[PageText] = []
        for page in raw_pages:
            cleaned = clean.clean_text(page.text)
            if cleaned:
                cleaned_pages.append(
                    PageText(page_number=page.page_number, text=cleaned)
                )
        if not cleaned_pages:
            raise IngestionError("No text remained after cleaning")

        text_chunks = chunk.chunk_pages(cleaned_pages)
        if not text_chunks:
            raise IngestionError("No chunks produced after cleaning")

        vectors: list[list[float]] | None = None
        model_name = ""
        if run_embeddings:
            from apps.knowledge.embeddings import EmbeddingError, get_embedding_service

            service = get_embedding_service()
            try:
                vectors = service.embed_many([c.content for c in text_chunks])
            except EmbeddingError as exc:
                raise IngestionError(str(exc)) from exc
            if len(vectors) != len(text_chunks):
                raise IngestionError("Embedding count does not match chunk count")
            model_name = service.model_name
            if model_name != settings.EMBEDDING_MODEL:
                raise IngestionError(
                    f"Embedding model mismatch: got {model_name!r}, "
                    f"expected {settings.EMBEDDING_MODEL!r}"
                )

        with transaction.atomic():
            document.chunks.all().delete()
            for index, text_chunk in enumerate(text_chunks):
                KnowledgeChunk.objects.create(
                    clinic=document.clinic,
                    document=document,
                    chunk_number=text_chunk.chunk_number,
                    page_number=text_chunk.page_start,
                    page_start=text_chunk.page_start,
                    page_end=text_chunk.page_end,
                    heading=text_chunk.heading or "",
                    chunk_type=text_chunk.chunk_type,
                    content=text_chunk.content,
                    token_count=text_chunk.token_count,
                    embedding=vectors[index] if vectors else None,
                    embedding_model=model_name if vectors else "",
                    metadata={
                        "estimated_token_count": text_chunk.token_count,
                        "chunk_type": text_chunk.chunk_type,
                    },
                )
            document.chunk_count = len(text_chunks)
            document.status = (
                DocumentStatus.INDEXED if vectors else DocumentStatus.CHUNKED
            )
            document.save(update_fields=["chunk_count", "status", "updated_at"])

        logger.info(
            "Ingested document %s — %s chunks (embeddings=%s)",
            document.id,
            document.chunk_count,
            bool(vectors),
        )
        return document

    except Exception as exc:
        logger.exception("Ingestion failed for document %s", document.id)
        _fail(document, str(exc))
        raise IngestionError(str(exc)) from exc


def _fail(document: Document, message: str) -> None:
    document.status = DocumentStatus.FAILED
    document.error_message = message[:2000]
    document.save(update_fields=["status", "error_message", "updated_at"])
