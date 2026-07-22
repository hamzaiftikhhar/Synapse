"""Orchestrate document ingestion: extract → clean → chunk → embed → persist."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction

from apps.knowledge.models import Document, DocumentStatus, KnowledgeChunk
from apps.knowledge.pipeline import chunk, clean, embed, extract

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


def ingest_document(document: Document) -> Document:
    """
    Run the full pipeline for one Document row.

    Updates status transitions: pending/processing → indexed | failed.
    """
    file_path = Path(settings.MEDIA_ROOT) / document.storage_path
    if not file_path.is_file():
        _fail(document, f"File not found: {document.storage_path}")
        raise IngestionError(document.error_message)

    document.status = DocumentStatus.PROCESSING
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])

    try:
        raw = extract.extract_text(file_path=file_path, file_type=document.file_type)
        normalized = clean.clean_text(raw)
        text_chunks = chunk.chunk_text(normalized)
        if not text_chunks:
            raise IngestionError("No chunks produced after cleaning")

        vectors = embed.embed_texts([c.content for c in text_chunks])

        with transaction.atomic():
            document.chunks.all().delete()
            for text_chunk, vector in zip(text_chunks, vectors, strict=True):
                KnowledgeChunk.objects.create(
                    clinic=document.clinic,
                    document=document,
                    chunk_number=text_chunk.chunk_number,
                    page_number=text_chunk.page_number,
                    content=text_chunk.content,
                    token_count=text_chunk.token_count,
                    embedding=vector,
                    embedding_model=settings.OPENAI_EMBEDDING_MODEL,
                )
            document.chunk_count = len(text_chunks)
            document.status = DocumentStatus.INDEXED
            document.save(
                update_fields=["chunk_count", "status", "updated_at"]
            )

        logger.info(
            "Ingested document %s — %s chunks",
            document.id,
            document.chunk_count,
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
