"""Document API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema

from apps.knowledge.models import ChunkType, DocumentStatus, ProcessingStage


class DocumentOut(Schema):
    id: UUID
    title: str
    file_name: str
    file_type: str
    file_size_bytes: int | None
    status: DocumentStatus
    processing_stage: ProcessingStage | str
    chunk_count: int
    error_message: str
    routing_summary: str = ""
    routing_keywords: list[str] = []
    uploaded_by_name: str | None = None
    uploaded_by_email: str | None = None
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUpdateIn(Schema):
    title: str | None = None
    routing_summary: str | None = None
    routing_keywords: list[str] | None = None


class ChunkOut(Schema):
    id: UUID
    chunk_number: int
    content: str
    heading: str
    page_start: int | None
    page_end: int | None
    page_number: int | None
    estimated_token_count: int | None
    chunk_type: ChunkType
    has_embedding: bool
    embedding_model: str
    created_at: datetime
