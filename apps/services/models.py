"""Clinic services."""

from django.db import models
from django.db.models import Q

from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class Service(TenantModel, TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    duration_min = models.PositiveSmallIntegerField(default=30)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "services"
        indexes = [
            models.Index(
                fields=["clinic", "is_active"],
                name="idx_services_active_live",
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return self.name
