"""Medical specialties."""

from django.db import models
from django.db.models import Q

from core.care_categories import CareCategory
from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class Specialty(TenantModel, TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    # Canonical, curated category (core.care_categories.CareCategory) --
    # normalizes each clinic's own free-text `name` against a controlled
    # vocabulary, the same way FHIR binds PractitionerRole.specialty to
    # the NUCC taxonomy rather than leaving it arbitrary text. Optional:
    # blank means "not yet categorized," not "uncategorizable" -- existing
    # clinics are unaffected until they (or an import) set one.
    category = models.CharField(
        max_length=32, choices=CareCategory.choices, blank=True, default=""
    )

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
