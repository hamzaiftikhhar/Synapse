"""Import job / record API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from ninja import Schema


class ImportRecordOut(Schema):
    id: UUID
    row_number: int
    raw_data: dict
    canonical_data: dict
    status: str
    validation_errors: list = []
    duplicate_match: dict | None = None
    created_entity_type: str = ""
    created_entity_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ImportJobCounts(Schema):
    needs_review: int = 0
    ready: int = 0
    duplicate: int = 0
    approved: int = 0
    rejected: int = 0
    committed: int = 0


class ImportJobOut(Schema):
    id: UUID
    record_type: str
    status: str
    file_name: str
    file_type: str
    file_size_bytes: int | None = None
    column_mapping: dict = {}
    total_row_count: int = 0
    error_message: str = ""
    metadata: dict = {}
    counts: ImportJobCounts
    committed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ImportMappingUpdateIn(Schema):
    # header -> target field name, or null to leave it unmapped
    mapping: dict[str, str | None]


class ImportRecordUpdateIn(Schema):
    values: dict[str, Any]


class ImportCommitOut(Schema):
    job: ImportJobOut
    created_count: int


class ImportBulkApproveOut(Schema):
    approved_count: int
    skipped_count: int
