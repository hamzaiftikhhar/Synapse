"""Spreadsheet data import — staging layer for bulk provider/service/
specialty onboarding.

Nothing here ever writes to Doctor/Service/Specialty directly. A row lives
as an ImportRecord (raw + mapped-but-unconfirmed data) until a human
approves it and the job is explicitly committed — see
apps/importer/services/committer.py.
"""

from django.conf import settings
from django.db import models

from core.models import TenantModel, TimestampedModel


class ImportRecordType(models.TextChoices):
    PROVIDERS = "providers", "Providers"
    SERVICES = "services", "Services"
    SPECIALTIES = "specialties", "Specialties"


class ImportJobStatus(models.TextChoices):
    UPLOADED = "uploaded", "Uploaded"
    PARSING = "parsing", "Parsing"
    MAPPED = "mapped", "Mapped"
    VALIDATED = "validated", "Validated"
    REVIEWED = "reviewed", "Reviewed"
    COMMITTED = "committed", "Committed"
    FAILED = "failed", "Failed"


class ImportRecordStatus(models.TextChoices):
    NEEDS_REVIEW = "needs_review", "Needs Review"
    READY = "ready", "Ready"
    DUPLICATE = "duplicate", "Possible Duplicate"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    COMMITTED = "committed", "Committed"


class ImportJob(TenantModel, TimestampedModel):
    record_type = models.CharField(max_length=16, choices=ImportRecordType.choices)
    status = models.CharField(
        max_length=16, choices=ImportJobStatus.choices, default=ImportJobStatus.UPLOADED
    )
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)
    storage_path = models.CharField(max_length=500)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    # {header: {"target": str|None, "confidence": float, "reason": str}}
    column_mapping = models.JSONField(default=dict, blank=True)
    # Up to IMPORTER_LLM_SAMPLE_ROWS rows shown to the LLM, kept for audit /
    # re-mapping without needing to re-read the source file.
    sample_rows = models.JSONField(default=list, blank=True)
    total_row_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_jobs",
    )
    committed_at = models.DateTimeField(null=True, blank=True)
    # {"mapping_source": "llm" | "heuristic_fallback"}
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "import_jobs"
        indexes = [
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["clinic", "record_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_record_type_display()} import — {self.file_name} ({self.status})"


class ImportRecord(TenantModel, TimestampedModel):
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="records")
    row_number = models.PositiveIntegerField()
    # Untouched original row — the staging layer the brief requires so
    # unmapped/unsupported columns are preserved, never silently dropped.
    raw_data = models.JSONField(default=dict)
    # {target_field: {"source": str, "value": Any, "confidence": float, "reason": str}}
    canonical_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ImportRecordStatus.choices,
        default=ImportRecordStatus.NEEDS_REVIEW,
    )
    validation_errors = models.JSONField(default=list, blank=True)
    # {"model": str, "id": str, "row_number": int|None, "similarity": float, "label": str}
    duplicate_match = models.JSONField(null=True, blank=True)
    created_entity_type = models.CharField(max_length=16, blank=True, default="")
    created_entity_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "import_records"
        constraints = [
            models.UniqueConstraint(
                fields=["job", "row_number"], name="uq_import_record_job_row"
            ),
        ]
        indexes = [
            models.Index(fields=["job", "status"]),
            models.Index(fields=["clinic", "job"]),
        ]

    def __str__(self) -> str:
        return f"Row {self.row_number} of {self.job_id} ({self.status})"
