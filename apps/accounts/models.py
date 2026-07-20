"""Clinic staff accounts for dashboard API login."""

from django.contrib.auth.models import User
from django.db import models


class ClinicStaff(models.Model):
    """
    Links a Django User to exactly one clinic.

  Used by POST /api/v1/auth/login — JWT embeds clinic_id for tenant isolation.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="clinic_staff",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="staff",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clinic_staff"
        verbose_name_plural = "clinic staff"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "clinic"],
                name="uq_clinic_staff_user_clinic",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} @ {self.clinic.slug}"
