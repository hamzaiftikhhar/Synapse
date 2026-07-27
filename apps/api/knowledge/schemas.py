"""Document API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema

from apps.knowledge.models import ChunkType, DocumentStatus


class DocumentOut(Schema):
    id: UUID
    title: str
    file_name: str
    file_type: str
    file_size_bytes: int | None
    status: DocumentStatus
    chunk_count: int
    error_message: str
    created_at: datetime
    updated_at: datetime


class DocumentUploadOut(DocumentOut):
    pass


class ChunkOut(Schema):
    id: UUID
    chunk_number: int
    content: str
    heading: str
    page_start: int | None
    page_end: int | None
    page_number: int | None  # alias of page_start
    estimated_token_count: int | None
    chunk_type: ChunkType
    has_embedding: bool
    embedding_model: str
    created_at: datetime
