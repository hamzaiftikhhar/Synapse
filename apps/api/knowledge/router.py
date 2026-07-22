"""Clinic knowledge documents — upload + list (staff JWT)."""

from uuid import UUID

from ninja import File, Form, Router, UploadedFile
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.knowledge.schemas import DocumentOut
from apps.knowledge.models import Document
from apps.knowledge.services import document_service as docs

router = Router(tags=["Knowledge"])


def _serialize(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        file_name=doc.file_name,
        file_type=doc.file_type,
        file_size_bytes=doc.file_size_bytes,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("", response=list[DocumentOut], auth=jwt_auth)
def list_documents(request):
    clinic = clinic_from(request)
    return [_serialize(d) for d in docs.list_documents(clinic=clinic)]


@router.post("", response={201: DocumentOut}, auth=jwt_auth)
def upload_document(
    request,
    title: str = Form(""),
    file: UploadedFile = File(...),  # noqa: B008
):
    """
    Upload a PDF and run the ingestion pipeline synchronously.

    Pipeline: store → extract → clean → chunk → embed → persist chunks.
    """
    clinic = clinic_from(request)
    try:
        document = docs.upload_document(
            clinic=clinic,
            uploaded_file=file,
            title=title,
            uploaded_by=request.auth.user,
            run_ingestion=True,
        )
    except docs.DocumentServiceError as exc:
        raise HttpError(400, str(exc)) from exc

    return 201, _serialize(document)


@router.get("/{document_id}", response=DocumentOut, auth=jwt_auth)
def get_document(request, document_id: UUID):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    return _serialize(document)


@router.post("/{document_id}/reindex", response=DocumentOut, auth=jwt_auth)
def reindex_document(request, document_id: UUID):
    """Re-run extract → chunk → embed for an existing document."""
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    try:
        document = docs.reindex_document(document)
    except Exception as exc:
        raise HttpError(500, str(exc)) from exc
    return _serialize(document)
