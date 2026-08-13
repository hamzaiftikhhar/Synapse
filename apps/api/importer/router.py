"""Spreadsheet data import — HTTP layer only. Business logic lives in
apps/importer/services/*; this file validates input, resolves the
tenant-scoped row, and serializes."""

from __future__ import annotations

from uuid import UUID

from django.conf import settings
from django.utils import timezone
from ninja import File, Form, Query, Router, UploadedFile
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.common.schemas import PaginatedOut

from apps.api.importer.schemas import (
    ImportBulkApproveOut,
    ImportCommitOut,
    ImportJobCounts,
    ImportJobOut,
    ImportMappingUpdateIn,
    ImportRecordOut,
    ImportRecordUpdateIn,
)
from apps.importer.models import (
    ImportJob,
    ImportJobStatus,
    ImportRecord,
    ImportRecordStatus,
    ImportRecordType,
)
from apps.importer.services import committer, duplicates, parser, pipeline, storage
from apps.importer.services.extractor import finalize_status
from apps.importer.target_schemas import required_fields_for, target_fields_for

router = Router(tags=["Import"])

_NAME_FIELD = {
    "providers": "full_name",
    "services": "name",
    "specialties": "name",
    "insurance": "provider_name",
}

_SUPPORTED_RECORD_TYPES = {t.value for t in ImportRecordType}


def _serialize_job(job: ImportJob) -> ImportJobOut:
    counts = {status.value: 0 for status in ImportRecordStatus}
    for row in job.records.values_list("status", flat=True):
        counts[row] = counts.get(row, 0) + 1
    return ImportJobOut(
        id=job.id,
        record_type=job.record_type,
        status=job.status,
        file_name=job.file_name,
        file_type=job.file_type,
        file_size_bytes=job.file_size_bytes,
        column_mapping=job.column_mapping,
        total_row_count=job.total_row_count,
        error_message=job.error_message,
        metadata=job.metadata,
        counts=ImportJobCounts(**counts),
        committed_at=job.committed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _serialize_record(record: ImportRecord) -> ImportRecordOut:
    return ImportRecordOut(
        id=record.id,
        row_number=record.row_number,
        raw_data=record.raw_data,
        canonical_data=record.canonical_data,
        status=record.status,
        validation_errors=record.validation_errors,
        duplicate_match=record.duplicate_match,
        created_entity_type=record.created_entity_type,
        created_entity_id=record.created_entity_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _get_job(clinic_id: UUID, job_id: UUID) -> ImportJob:
    try:
        return ImportJob.objects.get(clinic_id=clinic_id, id=job_id)
    except ImportJob.DoesNotExist:
        raise HttpError(404, "Import job not found") from None


def _get_record(clinic_id: UUID, job_id: UUID, record_id: UUID) -> ImportRecord:
    try:
        return ImportRecord.objects.get(clinic_id=clinic_id, job_id=job_id, id=record_id)
    except ImportRecord.DoesNotExist:
        raise HttpError(404, "Import record not found") from None


@router.post("/jobs", response={201: ImportJobOut}, auth=jwt_auth)
def create_import_job(
    request,
    record_type: str = Form(...),
    file: UploadedFile = File(...),  # noqa: B008
):
    clinic = clinic_from(request)
    if record_type not in _SUPPORTED_RECORD_TYPES:
        raise HttpError(400, "Unknown or not-yet-supported record type")

    try:
        parser.detect_file_type(file.name or "")
    except parser.ParserError as exc:
        raise HttpError(400, str(exc)) from exc

    max_size = getattr(settings, "IMPORTER_MAX_FILE_SIZE_BYTES", 5 * 1024 * 1024)
    if file.size and file.size > max_size:
        raise HttpError(400, f"File is too large (max {max_size // (1024 * 1024)}MB).")

    try:
        relative_path, size_bytes = storage.save_upload(clinic_id=clinic.id, uploaded_file=file)
    except storage.StorageError as exc:
        raise HttpError(400, str(exc)) from exc

    job = ImportJob.objects.create(
        clinic=clinic,
        record_type=record_type,
        status=ImportJobStatus.UPLOADED,
        file_name=file.name or "upload",
        file_type=(file.name or "").rsplit(".", 1)[-1].lower(),
        storage_path=relative_path,
        file_size_bytes=size_bytes,
        uploaded_by=request.auth.user,
    )
    pipeline.enqueue_import_pipeline(job.id)
    return 201, _serialize_job(job)


@router.get("/jobs", response=list[ImportJobOut], auth=jwt_auth)
def list_import_jobs(request, record_type: str | None = Query(None)):
    clinic = clinic_from(request)
    qs = ImportJob.objects.filter(clinic=clinic)
    if record_type:
        qs = qs.filter(record_type=record_type)
    return [_serialize_job(job) for job in qs.order_by("-created_at")]


@router.get("/jobs/{job_id}", response=ImportJobOut, auth=jwt_auth)
def get_import_job(request, job_id: UUID):
    return _serialize_job(_get_job(clinic_from(request).id, job_id))


@router.get("/jobs/{job_id}/records", response=PaginatedOut[ImportRecordOut], auth=jwt_auth)
def list_import_records(
    request,
    job_id: UUID,
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    job = _get_job(clinic.id, job_id)
    qs = job.records.all()
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("row_number")
    count = qs.count()
    results = [_serialize_record(r) for r in qs[offset : offset + limit]]
    return PaginatedOut(count=count, results=results)


@router.patch("/jobs/{job_id}/mapping", response=ImportJobOut, auth=jwt_auth)
def update_import_mapping(request, job_id: UUID, payload: ImportMappingUpdateIn):
    clinic = clinic_from(request)
    job = _get_job(clinic.id, job_id)
    if job.status not in {ImportJobStatus.MAPPED, ImportJobStatus.VALIDATED}:
        raise HttpError(400, f"Cannot edit mapping while the import is {job.status}.")

    allowed_targets = set(target_fields_for(job.record_type).keys())
    mapping = {}
    for header, target in payload.mapping.items():
        if target and target not in allowed_targets:
            raise HttpError(400, f"'{target}' is not a valid field for {job.record_type}.")
        mapping[header] = {
            "target": target,
            "confidence": 1.0 if target else 0.0,
            "reason": "Manually mapped" if target else "Left unmapped",
        }

    pipeline.apply_mapping(job, mapping)
    job.refresh_from_db()
    return _serialize_job(job)


@router.patch("/jobs/{job_id}/records/{record_id}", response=ImportRecordOut, auth=jwt_auth)
def update_import_record(request, job_id: UUID, record_id: UUID, payload: ImportRecordUpdateIn):
    clinic = clinic_from(request)
    record = _get_record(clinic.id, job_id, record_id)
    job = record.job
    target_fields = target_fields_for(job.record_type)
    name_field = _NAME_FIELD.get(job.record_type)
    name_touched = False

    identity_fields = {name_field} if name_field else set()
    if job.record_type == ImportRecordType.INSURANCE:
        identity_fields.update({"provider_name", "plan_name", "plan_type"})

    canonical = dict(record.canonical_data)
    for field, value in payload.values.items():
        if field not in target_fields:
            raise HttpError(400, f"'{field}' is not a valid field for {job.record_type}.")
        canonical[field] = {"source": "manual edit", "value": value, "confidence": 1.0, "reason": "Manually edited"}
        if field in identity_fields:
            name_touched = True

    errors = [
        {"field": field, "message": f"'{field}' is required but is missing."}
        for field in required_fields_for(job.record_type)
        if canonical.get(field, {}).get("value") in (None, "", [])
    ]

    duplicate_match = record.duplicate_match
    if name_touched and name_field:
        name_value = canonical.get(name_field, {}).get("value")
        extra = duplicates.extra_from_canonical(job.record_type, canonical)
        duplicate_match = (
            duplicates.find_duplicate(
                record_type=job.record_type,
                name=name_value,
                clinic=clinic,
                in_batch_names=[],
                extra=extra,
            )
            if name_value
            else None
        )

    threshold = getattr(settings, "IMPORTER_CONFIDENCE_THRESHOLD", 0.7)
    record.canonical_data = canonical
    record.validation_errors = errors
    record.duplicate_match = duplicate_match
    record.status = finalize_status(
        canonical_data=canonical,
        validation_errors=errors,
        duplicate_match=duplicate_match,
        confidence_threshold=threshold,
    )
    record.save(update_fields=["canonical_data", "validation_errors", "duplicate_match", "status", "updated_at"])
    return _serialize_record(record)


@router.post("/jobs/{job_id}/approve-all", response=ImportBulkApproveOut, auth=jwt_auth)
def approve_all_import_records(request, job_id: UUID):
    """Approve every row that is still pending and has no validation errors.

    Duplicates are included — the reviewer can reject those individually
    first. Rows with missing required fields are skipped, not forced.
    """
    clinic = clinic_from(request)
    job = _get_job(clinic.id, job_id)
    pending = job.records.exclude(
        status__in=[
            ImportRecordStatus.APPROVED,
            ImportRecordStatus.REJECTED,
            ImportRecordStatus.COMMITTED,
        ]
    )
    skipped = 0
    ids: list[UUID] = []
    for record in pending.only("id", "validation_errors"):
        if record.validation_errors:
            skipped += 1
            continue
        ids.append(record.id)
    if ids:
        ImportRecord.objects.filter(id__in=ids).update(
            status=ImportRecordStatus.APPROVED, updated_at=timezone.now()
        )
    return ImportBulkApproveOut(approved_count=len(ids), skipped_count=skipped)


@router.post("/jobs/{job_id}/records/{record_id}/approve", response=ImportRecordOut, auth=jwt_auth)
def approve_import_record(request, job_id: UUID, record_id: UUID):
    clinic = clinic_from(request)
    record = _get_record(clinic.id, job_id, record_id)
    if record.validation_errors:
        raise HttpError(400, "This record still has missing or invalid required fields.")
    record.status = ImportRecordStatus.APPROVED
    record.save(update_fields=["status", "updated_at"])
    return _serialize_record(record)


@router.post("/jobs/{job_id}/records/{record_id}/reject", response=ImportRecordOut, auth=jwt_auth)
def reject_import_record(request, job_id: UUID, record_id: UUID):
    clinic = clinic_from(request)
    record = _get_record(clinic.id, job_id, record_id)
    record.status = ImportRecordStatus.REJECTED
    record.save(update_fields=["status", "updated_at"])
    return _serialize_record(record)


@router.post("/jobs/{job_id}/commit", response=ImportCommitOut, auth=jwt_auth)
def commit_import_job(request, job_id: UUID):
    clinic = clinic_from(request)
    job = _get_job(clinic.id, job_id)
    try:
        created_count = committer.commit_job(job)
    except committer.CommitError as exc:
        raise HttpError(400, str(exc)) from exc
    job.refresh_from_db()
    return ImportCommitOut(job=_serialize_job(job), created_count=created_count)


@router.delete("/jobs/{job_id}", response={204: None}, auth=jwt_auth)
def delete_import_job(request, job_id: UUID):
    clinic = clinic_from(request)
    job = _get_job(clinic.id, job_id)
    if job.status == ImportJobStatus.COMMITTED:
        raise HttpError(400, "A committed import cannot be deleted.")
    storage.delete_file(job.storage_path)
    job.delete()
    return 204, None
