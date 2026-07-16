"""Insurance plans accepted by clinics."""

from django.db import models

from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class InsurancePlan(TenantModel, TimestampedModel, SoftDeleteModel):
    provider_name = models.CharField(max_length=255)
    plan_name = models.CharField(max_length=255, blank=True, default="")
    plan_type = models.CharField(max_length=50, blank=True, default="")
    is_accepted = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "insurance_plans"
        indexes = [
            models.Index(fields=["clinic", "is_accepted"]),
        ]

    def __str__(self) -> str:
        parts = [self.provider_name]
        if self.plan_name:
            parts.append(self.plan_name)
        return " — ".join(parts)
