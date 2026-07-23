"""Document upload / list / reindex — thin orchestration over storage + pipeline.

Why this file exists
--------------------
Routers must stay thin. This service owns:
  1. Validate file type
  2. Save bytes via storage.py
  3. Create the Document DB row (clinic-scoped)
  4. Start the ingestion pipeline

It does NOT extract text, chunk, or call OpenAI — that lives in pipeline/.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from django.core.files.uploadedfile import UploadedFile

from apps.accounts.models import User
from apps.clinics.models import Clinic
from apps.knowledge.models import Document, DocumentStatus
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
) -> Document:
    """
    Store the PDF and create a Document row, then optionally start ingestion.

    Data in
    -------
    clinic          : from staff JWT (clinic_from)
    uploaded_file   : multipart PDF
    title           : optional human label
    uploaded_by     : staff User from JWT

    Data out
    --------
    Document with status:
      - pending     → saved, ingest not started
      - processing  → ingest running (transient)
      - indexed     → pipeline succeeded
      - failed      → pipeline failed (error_message set)
    """
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
        uploaded_by=uploaded_by,
    )

    logger.info(
        "Document %s stored for clinic %s at %s",
        document.id,
        clinic.slug,
        relative_path,
    )

    if run_ingestion:
        try:
            start_ingestion(document)
        except IngestionError:
            document.refresh_from_db()
            # File is on disk and Document exists — caller still gets the row
            # with status=failed and error_message filled in.

    return document


def start_ingestion(document: Document) -> Document:
    """
    Kick off the pipeline for an existing Document.

    On failure, Document.status is set to failed (inside ingest) and
    IngestionError is raised after refresh.
    """
    try:
        return ingest_document(document)
    except IngestionError:
        document.refresh_from_db()
        raise


def reindex_document(document: Document) -> Document:
    """Reset status and re-run the full pipeline."""
    document.status = DocumentStatus.PENDING
    document.error_message = ""
    document.chunk_count = 0
    document.save(
        update_fields=["status", "error_message", "chunk_count", "updated_at"]
    )
    try:
        return start_ingestion(document)
    except IngestionError:
        document.refresh_from_db()
        return document


def get_document(*, clinic: Clinic, document_id: uuid.UUID) -> Document | None:
    return Document.objects.filter(
        clinic=clinic,
        pk=document_id,
        is_deleted=False,
    ).first()


def list_documents(*, clinic: Clinic) -> list[Document]:
    return list(
        Document.objects.filter(clinic=clinic, is_deleted=False).order_by("-created_at")
    )
