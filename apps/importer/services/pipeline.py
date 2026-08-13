"""Orchestrates parse -> guard -> map -> extract -> duplicate-check ->
persist ImportRecords. Two entry points:

- run_import_pipeline(job): the full run, right after upload.
- apply_mapping(job, mapping): re-runs extraction/validation/duplicates
  against the job's already-stored raw rows after a human edits the
  column mapping. No LLM call either way — mapping is confirmed by the
  time this runs.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction

from apps.importer.models import ImportJob, ImportJobStatus, ImportRecord
from apps.importer.services import duplicates, guard, mapper, parser, storage
from apps.importer.services.extractor import extract_record, finalize_status

logger = logging.getLogger(__name__)

LLM_SAMPLE_ROWS = 5

_NAME_FIELD = {
    "providers": "full_name",
    "services": "name",
    "specialties": "name",
    "insurance": "provider_name",
}


def _fail(job: ImportJob, message: str) -> None:
    job.status = ImportJobStatus.FAILED
    job.error_message = message
    job.save(update_fields=["status", "error_message", "updated_at"])


def _build_records(job: ImportJob, rows: list[dict]) -> list[ImportRecord]:
    threshold = getattr(settings, "IMPORTER_CONFIDENCE_THRESHOLD", 0.7)
    name_field = _NAME_FIELD.get(job.record_type)
    seen_names: list[str] = []
    records = []

    for index, row in enumerate(rows, start=1):
        canonical_data, errors = extract_record(row, job.column_mapping, job.record_type)
        name_value = (canonical_data.get(name_field) or {}).get("value") if name_field else None
        extra = duplicates.extra_from_canonical(job.record_type, canonical_data)
        duplicate_match = None
        if name_value:
            duplicate_match = duplicates.find_duplicate(
                record_type=job.record_type,
                name=name_value,
                clinic=job.clinic,
                in_batch_names=seen_names,
                extra=extra,
            )
            seen_names.append(duplicates.batch_token(job.record_type, name_value, extra))
        status = finalize_status(
            canonical_data=canonical_data,
            validation_errors=errors,
            duplicate_match=duplicate_match,
            confidence_threshold=threshold,
        )
        records.append(
            ImportRecord(
                clinic=job.clinic,
                job=job,
                row_number=index,
                raw_data=row,
                canonical_data=canonical_data,
                status=status,
                validation_errors=errors,
                duplicate_match=duplicate_match,
            )
        )
    return records


def run_import_pipeline(job: ImportJob) -> None:
    job.status = ImportJobStatus.PARSING
    job.save(update_fields=["status", "updated_at"])

    try:
        raw_bytes = storage.absolute_path(job.storage_path).read_bytes()
        table = parser.parse_file(file_name=job.file_name, raw_bytes=raw_bytes)
    except (parser.ParserError, OSError) as exc:
        _fail(job, str(exc))
        return

    patient_markers = guard.looks_like_patient_data(
        table.headers, record_type=job.record_type
    )
    if patient_markers:
        _fail(
            job,
            "This file looks like it contains patient or clinical records, not "
            "clinic setup data (flagged columns: " + ", ".join(patient_markers) + "). "
            "For safety it was not imported or sent to any AI service.",
        )
        return

    if not table.rows:
        _fail(job, "No data rows found in this file.")
        return

    mapping, mapping_source = mapper.map_columns(
        record_type=job.record_type,
        headers=table.headers,
        sample_rows=table.rows[:LLM_SAMPLE_ROWS],
    )

    job.column_mapping = mapping
    job.sample_rows = table.rows[:LLM_SAMPLE_ROWS]
    job.total_row_count = len(table.rows)
    job.metadata = {**job.metadata, "mapping_source": mapping_source}

    records = _build_records(job, table.rows)
    with transaction.atomic():
        ImportRecord.objects.filter(job=job).delete()
        ImportRecord.objects.bulk_create(records)
        job.status = ImportJobStatus.MAPPED
        job.save(
            update_fields=[
                "column_mapping", "sample_rows", "total_row_count",
                "metadata", "status", "updated_at",
            ]
        )


def apply_mapping(job: ImportJob, mapping: dict) -> None:
    """Re-run extraction/validation/duplicates for every already-stored
    row against a human-edited mapping — no re-parse, no LLM call."""
    job.column_mapping = mapping
    existing = list(job.records.order_by("row_number"))
    rows = [record.raw_data for record in existing]
    rebuilt = _build_records(job, rows)

    with transaction.atomic():
        for old, new in zip(existing, rebuilt):
            old.canonical_data = new.canonical_data
            old.validation_errors = new.validation_errors
            old.duplicate_match = new.duplicate_match
            old.status = new.status
            old.save(
                update_fields=["canonical_data", "validation_errors", "duplicate_match", "status", "updated_at"]
            )
        job.status = ImportJobStatus.MAPPED
        job.save(update_fields=["column_mapping", "status", "updated_at"])


def enqueue_import_pipeline(job_id) -> None:
    """Background thread, same pattern as
    apps/knowledge/services/document_service.py::enqueue_ingestion."""

    def _run() -> None:
        close_old_connections()
        try:
            job = ImportJob.objects.filter(pk=job_id).first()
            if job is None:
                return
            run_import_pipeline(job)
        except Exception:
            logger.exception("Import pipeline failed for job %s", job_id)
            job = ImportJob.objects.filter(pk=job_id).first()
            if job is not None and job.status != ImportJobStatus.FAILED:
                _fail(job, "Something went wrong processing this file. Please try again.")
        finally:
            close_old_connections()

    threading.Thread(target=_run, name=f"import-{job_id}", daemon=True).start()
