"""
Shared abstract base models for Synapse domain tables.
"""

from django.db import models

from core.uuid import UuidV7, uuid7


class UUIDModel(models.Model):
    """
    UUID primary key for all domain tables.

    Uses UUIDv7 (time-ordered):
    - Python default: core.uuid.uuid7 for ORM creates
    - DB default: PostgreSQL 18 uuidv7() for SQL/raw inserts
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid7,
        db_default=UuidV7(),
        editable=False,
    )

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    Soft delete for catalog entities (doctors, services, etc.).

    No standalone index on is_deleted — feature apps use partial indexes
    (… WHERE is_deleted = false) for active-row lookups.
    """

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class TenantModel(UUIDModel):
    """Tenant-scoped model with clinic FK for multi-tenancy."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    class Meta:
        abstract = True
