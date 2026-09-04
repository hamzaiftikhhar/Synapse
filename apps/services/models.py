"""Clinic services."""

from django.db import models
from django.db.models import Q

from core.care_categories import CareCategory
from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class Service(TenantModel, TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    code = models.CharField(max_length=64, blank=True, default="")
    # Same canonical, curated vocabulary as Specialty.category (see
    # core/care_categories.py) -- kept at max_length=100, wider than the
    # longest CareCategory value needs, since this predates the enum and
    # narrowing it isn't necessary for the choices constraint to apply.
    category = models.CharField(
        max_length=100, choices=CareCategory.choices, blank=True, default=""
    )
    duration_min = models.PositiveSmallIntegerField(default=30)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "services"
        indexes = [
            models.Index(
                fields=["clinic", "is_active"],
                name="idx_services_active_live",
                condition=Q(is_deleted=False),
            ),
            models.Index(
                fields=["clinic", "code"],
                name="idx_services_code_live",
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return self.name
