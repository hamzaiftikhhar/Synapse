"""
Shared abstract base models for Synapse.

Domain models are implemented in Phase 3. These bases establish UUID PKs,
timestamps, tenant scoping, and soft-delete conventions.
"""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """UUID primary key for all domain tables."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

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


class TenantModel(UUIDModel, TimestampedModel):
    """
    Tenant-scoped model with clinic FK.

    clinic FK is wired in Phase 3 once apps.clinics.Clinic exists.
    Subclasses override / declare clinic explicitly until then.
    """

    class Meta:
        abstract = True
