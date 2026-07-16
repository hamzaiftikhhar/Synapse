"""Medical specialties."""

from django.db import models
from django.db.models import Q

from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class Specialty(TenantModel, TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "specialties"
        verbose_name_plural = "specialties"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "slug"],
                name="uq_specialty_clinic_slug",
            ),
        ]
        indexes = [
            models.Index(
                fields=["clinic", "is_active"],
                name="idx_spec_active_live",
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return self.name
