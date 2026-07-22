"""Patients."""

from django.db import models
from django.db.models import Q

from core.models import TenantModel, TimestampedModel


class Patient(TenantModel, TimestampedModel):
    phone = models.CharField(max_length=20)  # required for OTP
    email = models.EmailField(blank=True, default="")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    preferred_language = models.CharField(max_length=10, default="en")
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when phone OTP verification succeeds.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta: #Meta is used to define the database table name and constraints and indexes
        db_table = "patients"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "phone"],
                name="uq_patient_clinic_phone",
            ),
            models.UniqueConstraint(
                fields=["clinic", "email"],
                condition=~Q(email=""),
                name="uq_patient_clinic_email",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "first_name"]),
            models.Index(fields=["clinic", "last_name"]),
        ]

    @property #what it is called in Django @property? getter method
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.full_name or self.phone
