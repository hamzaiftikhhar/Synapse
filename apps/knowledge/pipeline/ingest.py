"""Orchestrate document ingestion: extract → clean → chunk → (optional embed) → persist."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.knowledge.models import (
    Document,
    DocumentStatus,
    KnowledgeChunk,
    ProcessingStage,
)
from apps.knowledge.pipeline import chunk, clean, extract
from apps.knowledge.pipeline.extract import PageText
from apps.knowledge.services import storage

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


class IngestionCancelled(IngestionError):
    pass


def ingest_document(
    document: Document,
    *,
    run_embeddings: bool | None = None,
) -> Document:
    if run_embeddings is None:
        run_embeddings = settings.KNOWLEDGE_RUN_EMBEDDINGS

    file_path = storage.absolute_path(document.storage_path)
    if not file_path.is_file():
        _fail(document, f"File not found: {document.storage_path}")
        raise IngestionError(document.error_message)

    _set_stage(document, DocumentStatus.PROCESSING, ProcessingStage.EXTRACTING)
    logger.info(
        "document_processing_started document=%s clinic=%s file_type=%s",
        document.id, document.clinic_id, document.file_type,
    )
    _raise_if_cancelled(document)

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

        _raise_if_cancelled(document)
        _set_stage(document, DocumentStatus.PROCESSING, ProcessingStage.CHUNKING)

        text_chunks = chunk.chunk_pages(cleaned_pages)
        if not text_chunks:
            raise IngestionError("No chunks produced after cleaning")

        vectors: list[list[float]] | None = None
        model_name = ""
        if run_embeddings:
            _raise_if_cancelled(document)
            _set_stage(document, DocumentStatus.PROCESSING, ProcessingStage.EMBEDDING)
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

        _raise_if_cancelled(document)
        _set_stage(document, DocumentStatus.PROCESSING, ProcessingStage.STORING)

        with transaction.atomic():
            document.chunks.all().delete()
            for index, text_chunk in enumerate(text_chunks):
                vector = vectors[index] if vectors else None
                if run_embeddings and vector is None:
                    raise IngestionError(
                        f"Missing embedding for chunk {text_chunk.chunk_number}"
                    )
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
                    embedding=vector,
                    embedding_model=model_name if vectors else "",
                    metadata={
                        "estimated_token_count": text_chunk.token_count,
                        "chunk_type": text_chunk.chunk_type,
                    },
                )
            document.refresh_from_db()
            if _cancel_requested(document):
                raise IngestionCancelled("Processing cancelled")

            document.chunk_count = len(text_chunks)
            document.status = (
                DocumentStatus.INDEXED if vectors else DocumentStatus.CHUNKED
            )
            document.processing_stage = ProcessingStage.COMPLETED
            if not (document.routing_summary or "").strip():
                document.routing_summary = _routing_summary_from_chunks(
                    document.title, text_chunks
                )
            if not document.routing_keywords:
                document.routing_keywords = _routing_keywords_from_text(
                    document.title,
                    " ".join(c.content for c in text_chunks[:3]),
                )
            meta = dict(document.metadata or {})
            meta.pop("cancel_requested", None)
            meta["processing_completed_at"] = timezone.now().isoformat()
            document.metadata = meta
            document.save(
                update_fields=[
                    "chunk_count",
                    "status",
                    "processing_stage",
                    "routing_summary",
                    "routing_keywords",
                    "metadata",
                    "updated_at",
                ]
            )

        logger.info(
            "document_processing_completed document=%s chunks=%s embeddings=%s",
            document.id,
            document.chunk_count,
            bool(vectors),
        )
        return document

    except IngestionCancelled as exc:
        _cancel(document, str(exc))
        raise
    except Exception as exc:
        logger.exception("document_processing_failed document=%s", document.id)
        _fail(document, str(exc))
        raise IngestionError(str(exc)) from exc


def _cancel_requested(document: Document) -> bool:
    document.refresh_from_db(fields=["metadata", "status"])
    meta = document.metadata if isinstance(document.metadata, dict) else {}
    return bool(meta.get("cancel_requested")) or document.status == DocumentStatus.CANCELLED


def _raise_if_cancelled(document: Document) -> None:
    if _cancel_requested(document):
        raise IngestionCancelled("Processing cancelled")


def _set_stage(
    document: Document,
    status: str,
    stage: str,
) -> None:
    document.status = status
    document.processing_stage = stage
    document.error_message = ""
    document.save(
        update_fields=["status", "processing_stage", "error_message", "updated_at"]
    )


def _fail(document: Document, message: str) -> None:
    document.status = DocumentStatus.FAILED
    document.processing_stage = ProcessingStage.FAILED
    document.error_message = message[:2000]
    meta = dict(document.metadata or {})
    meta["processing_completed_at"] = timezone.now().isoformat()
    document.metadata = meta
    document.save(
        update_fields=[
            "status",
            "processing_stage",
            "error_message",
            "metadata",
            "updated_at",
        ]
    )


def _cancel(document: Document, message: str) -> None:
    document.status = DocumentStatus.CANCELLED
    document.processing_stage = ProcessingStage.CANCELLED
    document.error_message = (message or "Cancelled")[:2000]
    meta = dict(document.metadata or {})
    meta["cancel_requested"] = False
    meta["processing_completed_at"] = timezone.now().isoformat()
    document.metadata = meta
    document.save(
        update_fields=[
            "status",
            "processing_stage",
            "error_message",
            "metadata",
            "updated_at",
        ]
    )


def _routing_summary_from_chunks(title: str, text_chunks: list) -> str:
    first = ""
    if text_chunks:
        first = " ".join((text_chunks[0].content or "").split())[:240]
    if first:
        return f"{title}. {first}"
    return f"Clinic document: {title}."


def _routing_keywords_from_text(title: str, text: str) -> list[str]:
    import re

    blob = f"{title} {text}".lower()
    # Domain-agnostic seed cues + title tokens + frequent content tokens
    seed = (
        "insurance", "coverage", "copay", "cancel", "cancellation", "booking",
        "policy", "hours", "vaccination", "pediatric", "child", "membership",
        "pricing", "refund", "referral", "appointment", "deposit", "arrival",
        "arrive", "post-op", "postoperative", "extraction", "orthodontic",
        "protocol", "fee", "emergency", "instructions", "restriction",
    )
    found: list[str] = [k for k in seed if k.replace("-", " ") in blob or k in blob]
    for token in re.findall(r"[a-z]{4,}", title.lower()):
        if token not in found and token not in {"patient", "document", "clinic", "comprehensive"}:
            found.append(token)
    # Frequent content tokens (dynamic per document)
    counts: dict[str, int] = {}
    for token in re.findall(r"[a-z]{5,}", text.lower()):
        if token in {
            "patient", "patients", "clinic", "please", "should", "before",
            "after", "their", "there", "which", "would", "could", "about",
        }:
            continue
        counts[token] = counts.get(token, 0) + 1
    for token, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if token not in found:
            found.append(token)
        if len(found) >= 12:
            break
    return found[:12]
