"""Clinic knowledge documents — HTTP layer only (staff JWT)."""

from uuid import UUID

from django.http import FileResponse
from ninja import File, Form, Router, UploadedFile
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.knowledge.schemas import ChunkOut, DocumentOut, DocumentUpdateIn
from apps.knowledge.models import Document, KnowledgeChunk
from apps.knowledge.services import document_service as docs
from apps.knowledge.services import storage

router = Router(tags=["Knowledge"])


def _uploaded_by_name(doc: Document) -> str | None:
    user = doc.uploaded_by
    if user is None:
        return None
    name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    return name or getattr(user, "email", None) or getattr(user, "username", None)


def _meta_dt(doc: Document, key: str):
    meta = doc.metadata if isinstance(doc.metadata, dict) else {}
    raw = meta.get(key)
    if not raw:
        return None
    if hasattr(raw, "isoformat"):
        return raw
    from django.utils.dateparse import parse_datetime

    return parse_datetime(str(raw)) if raw else None


def _serialize(doc: Document) -> DocumentOut:
    user = doc.uploaded_by
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        file_name=doc.file_name,
        file_type=doc.file_type,
        file_size_bytes=doc.file_size_bytes,
        status=doc.status,
        processing_stage=getattr(doc, "processing_stage", "") or "queued",
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        routing_summary=getattr(doc, "routing_summary", "") or "",
        routing_keywords=list(getattr(doc, "routing_keywords", None) or []),
        uploaded_by_name=_uploaded_by_name(doc),
        uploaded_by_email=getattr(user, "email", None) if user else None,
        processing_started_at=_meta_dt(doc, "processing_started_at"),
        processing_finished_at=_meta_dt(doc, "processing_completed_at"),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _serialize_chunk(row: KnowledgeChunk) -> ChunkOut:
    page_start = row.page_start if row.page_start is not None else row.page_number
    return ChunkOut(
        id=row.id,
        chunk_number=row.chunk_number,
        content=row.content,
        heading=row.heading or "",
        page_start=page_start,
        page_end=row.page_end if row.page_end is not None else page_start,
        page_number=page_start,
        estimated_token_count=row.token_count,
        chunk_type=row.chunk_type,
        has_embedding=row.embedding is not None,
        embedding_model=row.embedding_model,
        created_at=row.created_at,
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
    """Upload a PDF; ingestion runs in the background (poll GET for status/stage)."""
    clinic = clinic_from(request)
    try:
        document = docs.upload_document(
            clinic=clinic,
            uploaded_file=file,
            title=title,
            uploaded_by=request.auth.user,
            run_ingestion=True,
            async_ingest=True,
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


@router.patch("/{document_id}", response=DocumentOut, auth=jwt_auth)
def update_document(request, document_id: UUID, payload: DocumentUpdateIn):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    try:
        document = docs.update_document(
            document,
            title=payload.title,
            routing_summary=payload.routing_summary,
            routing_keywords=payload.routing_keywords,
        )
    except docs.DocumentServiceError as exc:
        raise HttpError(400, str(exc)) from exc
    return _serialize(document)


@router.delete("/{document_id}", response={204: None}, auth=jwt_auth)
def delete_document(request, document_id: UUID):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    docs.soft_delete_document(document)
    return 204, None


@router.get("/{document_id}/download", auth=jwt_auth)
def download_document(request, document_id: UUID, inline: bool = False):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    path = storage.absolute_path(document.storage_path)
    if not path.is_file():
        raise HttpError(404, "File missing on disk")
    response = FileResponse(
        path.open("rb"),
        as_attachment=not inline,
        filename=document.file_name or "document.pdf",
        content_type="application/pdf",
    )
    return response


@router.get("/{document_id}/chunks", response=list[ChunkOut], auth=jwt_auth)
def list_chunks(request, document_id: UUID):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    rows = KnowledgeChunk.objects.filter(
        clinic=clinic, document=document
    ).order_by("chunk_number")
    return [_serialize_chunk(row) for row in rows]


@router.post("/{document_id}/reindex", response=DocumentOut, auth=jwt_auth)
def reindex_document(request, document_id: UUID):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    try:
        document = docs.reindex_document(document, async_ingest=True)
    except docs.DocumentServiceError as exc:
        raise HttpError(400, str(exc)) from exc
    return _serialize(document)


@router.post("/{document_id}/cancel", response=DocumentOut, auth=jwt_auth)
def cancel_document(request, document_id: UUID):
    clinic = clinic_from(request)
    document = docs.get_document(clinic=clinic, document_id=document_id)
    if document is None:
        raise HttpError(404, "Document not found")
    try:
        document = docs.request_cancel(document)
    except docs.DocumentServiceError as exc:
        raise HttpError(400, str(exc)) from exc
    return _serialize(document)
