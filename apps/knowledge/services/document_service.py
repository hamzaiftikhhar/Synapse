"""Document upload / list / reindex / mutate — orchestration over storage + pipeline."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from django.core.files.uploadedfile import UploadedFile
from django.db import close_old_connections
from django.utils import timezone

from apps.accounts.models import User
from apps.clinics.models import Clinic
from apps.knowledge.models import Document, DocumentStatus, ProcessingStage
from apps.knowledge.pipeline.ingest import IngestionError, ingest_document
from apps.knowledge.services import storage

logger = logging.getLogger(__name__)


class DocumentServiceError(Exception):
    """User-facing upload error (bad file type, storage failure, …)."""


ALLOWED_FILE_TYPES = {"pdf"}


def upload_document(
    *,
    clinic: Clinic,
    uploaded_file: UploadedFile,
    title: str = "",
    uploaded_by: User | None = None,
    run_ingestion: bool = True,
    async_ingest: bool = True,
) -> Document:
    ext = Path(uploaded_file.name or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED_FILE_TYPES:
        raise DocumentServiceError(
            f"Unsupported file type: {ext or 'unknown'}. Only PDF is allowed."
        )

    try:
        relative_path, size_bytes = storage.save_upload(
            clinic_id=clinic.id,
            uploaded_file=uploaded_file,
        )
    except storage.StorageError as exc:
        raise DocumentServiceError(str(exc)) from exc

    document = Document.objects.create(
        clinic=clinic,
        title=(title or "").strip() or Path(uploaded_file.name or "document").stem,
        file_name=Path(uploaded_file.name or "document.pdf").name,
        file_type=ext,
        storage_path=relative_path,
        file_size_bytes=size_bytes,
        status=DocumentStatus.PENDING,
        processing_stage=ProcessingStage.QUEUED,
        uploaded_by=uploaded_by,
        metadata={"processing_started_at": timezone.now().isoformat()},
    )

    logger.info(
        "Document %s stored for clinic %s at %s",
        document.id,
        clinic.slug,
        relative_path,
    )

    if run_ingestion:
        if async_ingest:
            enqueue_ingestion(document.id)
        else:
            try:
                start_ingestion(document)
            except IngestionError:
                document.refresh_from_db()

    return document


def enqueue_ingestion(document_id: uuid.UUID) -> None:
    """Run ingest in a background thread so upload returns immediately for polling."""

    def _run() -> None:
        close_old_connections()
        try:
            document = Document.objects.filter(pk=document_id, is_deleted=False).first()
            if document is None:
                return
            start_ingestion(document)
        except Exception:
            logger.exception("Background ingestion failed for %s", document_id)
        finally:
            close_old_connections()

    threading.Thread(
        target=_run,
        name=f"ingest-{document_id}",
        daemon=True,
    ).start()


def start_ingestion(document: Document) -> Document:
    document.refresh_from_db()
    meta = document.metadata if isinstance(document.metadata, dict) else {}
    if (
        document.status == DocumentStatus.CANCELLED
        or meta.get("cancel_requested")
    ):
        document.status = DocumentStatus.CANCELLED
        document.processing_stage = ProcessingStage.CANCELLED
        document.save(
            update_fields=["status", "processing_stage", "updated_at"]
        )
        return document
    try:
        return ingest_document(document)
    except IngestionError:
        document.refresh_from_db()
        raise


def reindex_document(document: Document, *, async_ingest: bool = True) -> Document:
    document.status = DocumentStatus.PENDING
    document.processing_stage = ProcessingStage.QUEUED
    document.error_message = ""
    document.chunk_count = 0
    meta = dict(document.metadata or {})
    meta.pop("cancel_requested", None)
    meta["processing_started_at"] = timezone.now().isoformat()
    document.metadata = meta
    document.save(
        update_fields=[
            "status",
            "processing_stage",
            "error_message",
            "chunk_count",
            "metadata",
            "updated_at",
        ]
    )
    if async_ingest:
        enqueue_ingestion(document.id)
        document.refresh_from_db()
        return document
    try:
        return start_ingestion(document)
    except IngestionError:
        document.refresh_from_db()
        return document


def update_document(
    document: Document,
    *,
    title: str | None = None,
    routing_summary: str | None = None,
    routing_keywords: list[str] | None = None,
) -> Document:
    fields: list[str] = ["updated_at"]
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            raise DocumentServiceError("Title cannot be empty")
        document.title = cleaned[:255]
        fields.append("title")
    if routing_summary is not None:
        document.routing_summary = routing_summary.strip()[:2000]
        fields.append("routing_summary")
    if routing_keywords is not None:
        document.routing_keywords = [
            str(k).strip()[:40] for k in routing_keywords if str(k).strip()
        ][:20]
        fields.append("routing_keywords")
    document.save(update_fields=fields)
    return document


def soft_delete_document(document: Document) -> Document:
    document.is_deleted = True
    document.deleted_at = timezone.now()
    document.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    return document


def request_cancel(document: Document) -> Document:
    if document.status not in {
        DocumentStatus.PENDING,
        DocumentStatus.PROCESSING,
    }:
        raise DocumentServiceError("Only queued or processing documents can be cancelled")
    meta = dict(document.metadata or {})
    meta["cancel_requested"] = True
    document.metadata = meta
    # Pending jobs that haven't started yet flip immediately
    if document.status == DocumentStatus.PENDING:
        document.status = DocumentStatus.CANCELLED
        document.processing_stage = ProcessingStage.CANCELLED
        document.error_message = "Cancelled before processing started"
        document.save(
            update_fields=[
                "metadata",
                "status",
                "processing_stage",
                "error_message",
                "updated_at",
            ]
        )
    else:
        document.save(update_fields=["metadata", "updated_at"])
    return document


def get_document(*, clinic: Clinic, document_id: uuid.UUID) -> Document | None:
    return (
        Document.objects.filter(
            clinic=clinic,
            pk=document_id,
            is_deleted=False,
        )
        .select_related("uploaded_by")
        .first()
    )


def list_documents(*, clinic: Clinic) -> list[Document]:
    return list(
        Document.objects.filter(clinic=clinic, is_deleted=False)
        .select_related("uploaded_by")
        .order_by("-created_at")
    )
