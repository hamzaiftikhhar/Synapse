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
    """Soft delete for catalog entities (doctors, services, etc.)."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class TenantModel(UUIDModel):
    """Tenant-scoped model with clinic FK for multi-tenancy."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="%(class)ss",# this is a string interpolation. It is used to dynamically generate the related name for the clinic foreign key field.
    )

    class Meta:
        abstract = True
