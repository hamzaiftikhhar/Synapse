"""Document upload and ingestion orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from apps.accounts.models import User
from apps.clinics.models import Clinic
from apps.knowledge.models import Document, DocumentStatus
from apps.knowledge.pipeline.ingest import ingest_document


class DocumentServiceError(Exception):
    pass


ALLOWED_FILE_TYPES = {"pdf"}


def _storage_path(clinic_id: uuid.UUID, file_name: str) -> str:
    safe_name = Path(file_name).name
    return f"clinics/{clinic_id}/documents/{uuid.uuid4()}/{safe_name}"


def upload_document(
    *,
    clinic: Clinic,
    uploaded_file: UploadedFile,
    title: str,
    uploaded_by: User | None = None,
    run_ingestion: bool = True,
) -> Document:
    """
    Store file on disk, create Document row, optionally run ingestion pipeline.
    """
    ext = Path(uploaded_file.name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_FILE_TYPES:
        raise DocumentServiceError(f"Unsupported file type: {ext or 'unknown'}")

    relative_path = _storage_path(clinic.id, uploaded_file.name)
    absolute_path = Path(settings.MEDIA_ROOT) / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)

    with absolute_path.open("wb") as dest:
        for chunk in uploaded_file.chunks():
            dest.write(chunk)

    document = Document.objects.create(
        clinic=clinic,
        title=title.strip() or Path(uploaded_file.name).stem,
        file_name=Path(uploaded_file.name).name,
        file_type=ext,
        storage_path=relative_path,
        file_size_bytes=uploaded_file.size,
        status=DocumentStatus.PENDING,
        uploaded_by=uploaded_by,
    )

    if run_ingestion:
        ingest_document(document)

    return document


def reindex_document(document: Document) -> Document:
    """Re-run ingestion pipeline on an existing document."""
    document.status = DocumentStatus.PENDING
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])
    return ingest_document(document)


def get_document(*, clinic: Clinic, document_id: uuid.UUID) -> Document | None:
    return Document.objects.filter(
        clinic=clinic,
        pk=document_id,
        is_deleted=False,
    ).first()


def list_documents(*, clinic: Clinic) -> list[Document]:
    return list(
        Document.objects.filter(clinic=clinic, is_deleted=False).order_by(
            "-created_at"
        )
    )
