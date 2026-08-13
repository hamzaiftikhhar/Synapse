"""Turns APPROVED ImportRecords into real production rows.

The only place an import job is allowed to touch Doctor/Service/Specialty/InsurancePlan
— and only through the same creation functions the manual onboarding UI
already uses, so nothing about readiness detection or business logic gets
a second code path. Single atomic transaction: any failure rolls back the
entire batch, never a half-imported clinic.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.doctors.services.doctor_service import create_doctor
from apps.importer.models import ImportJob, ImportJobStatus, ImportRecordStatus, ImportRecordType
from apps.insurance.services.insurance_service import create_insurance_plan
from apps.services.services.service_service import create_service
from apps.specialties.services.specialty_service import create_specialty


class CommitError(Exception):
    """Job could not be committed — never partially."""


def _create_fn_for(record_type: str) -> tuple:
    """Looked up by name (not a dict frozen at import time) so tests can
    mock apps.importer.services.committer.create_service/create_doctor/
    create_specialty directly."""
    if record_type == ImportRecordType.SERVICES:
        return create_service, "service"
    if record_type == ImportRecordType.PROVIDERS:
        return create_doctor, "doctor"
    if record_type == ImportRecordType.SPECIALTIES:
        return create_specialty, "specialty"
    if record_type == ImportRecordType.INSURANCE:
        return create_insurance_plan, "insurance"
    raise CommitError(f"Importing {record_type} isn't supported yet.")  # pragma: no cover


def _values_for_create(canonical_data: dict) -> dict:
    return {
        field: entry["value"]
        for field, entry in canonical_data.items()
        if entry.get("value") not in (None, "", [])
    }


def commit_job(job: ImportJob) -> int:
    if job.status == ImportJobStatus.COMMITTED:
        raise CommitError("This import has already been committed.")

    pending = job.records.exclude(
        status__in=[ImportRecordStatus.APPROVED, ImportRecordStatus.REJECTED]
    )
    if pending.exists():
        raise CommitError(
            f"{pending.count()} record(s) still need review before this import can be committed."
        )

    approved = list(job.records.filter(status=ImportRecordStatus.APPROVED).order_by("row_number"))
    if not approved:
        raise CommitError("No approved records to commit.")

    create_fn, entity_type = _create_fn_for(job.record_type)

    created_count = 0
    with transaction.atomic():
        for record in approved:
            entity = create_fn(clinic=job.clinic, **_values_for_create(record.canonical_data))
            record.status = ImportRecordStatus.COMMITTED
            record.created_entity_type = entity_type
            record.created_entity_id = entity.id
            record.save(update_fields=["status", "created_entity_type", "created_entity_id", "updated_at"])
            created_count += 1

        job.status = ImportJobStatus.COMMITTED
        job.committed_at = timezone.now()
        job.save(update_fields=["status", "committed_at", "updated_at"])

    return created_count
